"""GKE target, Rollouts and namespace RBAC verification; no EKS changes.

15-minute verification credentials stay in memory. App writes use server dry-run.
--google-service-account uses operator IAM impersonation, not the EKS WIF exchange.
Requires PyYAML only when --rendered-overlay is provided.
"""

import argparse
import base64
import datetime as dt
import json
from pathlib import Path
import ssl
import subprocess
import urllib.error
import urllib.request


def kubectl(kubeconfig, *arguments):
    result = subprocess.run(
        ["kubectl", "--kubeconfig", kubeconfig, "--request-timeout=30s", *arguments],
        capture_output=True, text=True, encoding="utf-8", check=False,
    )
    if result.returncode:
        # Never relay a credential-bearing stdout/stderr to logs.
        raise RuntimeError(f"kubectl failed ({result.returncode}): {arguments[0]}")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kubeconfig", required=True)
    parser.add_argument("--rendered-overlay", "--rendered-manifests", dest="rendered_overlay",
                        help="Combined Kustomize output from every Application source, including analysis/default")
    parser.add_argument("--google-service-account", help="Verify using a Google service account; operator needs scoped getAccessToken permission")
    parser.add_argument("--verify-rollout-status", action="store_true",
                        help="Read and server dry-run patch the existing sample-app Rollout status; does not promote")
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    target = json.loads(Path(__file__).with_name("target.json").read_text(encoding="utf-8"))
    config = json.loads(kubectl(options.kubeconfig, "config", "view", "--minify", "--raw", "-o", "json"))
    cluster = config["clusters"][0]["cluster"]
    if cluster["server"].rstrip("/") != target["server"]:
        raise RuntimeError("GKE API address mismatch")
    uid = json.loads(kubectl(options.kubeconfig, "get", "--raw", "/api/v1/namespaces/kube-system"))["metadata"]["uid"]
    if uid != target["kubeSystemUid"]:
        raise RuntimeError("GKE UID mismatch")
    deployment = json.loads(kubectl(options.kubeconfig, "get", "deployment", "argo-rollouts", "-n", "argo-rollouts", "-o", "json"))
    if deployment["status"].get("availableReplicas") != 1:
        raise RuntimeError("Rollouts controller is not available")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    if container["image"] != "quay.io/argoproj/argo-rollouts:v1.10.0":
        raise RuntimeError("Unexpected Rollouts version")
    established = []
    for name in ("rollouts", "analysistemplates", "analysisruns", "experiments", "clusteranalysistemplates"):
        crd = json.loads(kubectl(options.kubeconfig, "get", "crd", name + ".argoproj.io", "-o", "json"))
        if not any(c["type"] == "Established" and c["status"] == "True" for c in crd["status"]["conditions"]):
            raise RuntimeError("CRD not established: " + name)
        established.append(name)

    ca = base64.b64decode(cluster["certificate-authority-data"]).decode("ascii")
    context = ssl.create_default_context(cadata=ca)
    if options.google_service_account:
        expected = json.loads(Path(__file__).with_name("federation.json").read_text(encoding="utf-8"))
        if options.google_service_account != expected["serviceAccountEmail"]:
            raise RuntimeError("Unexpected Google service account")
        # On Windows gcloud.cmd must be resolved explicitly; all output stays in memory.
        import shutil
        import os
        cloud_path = shutil.which("gcloud.cmd" if os.name == "nt" else "gcloud")
        if not cloud_path:
            raise RuntimeError("gcloud is unavailable")
        cloud = subprocess.run([cloud_path, "auth", "print-access-token"],
                               capture_output=True, text=True, encoding="utf-8", check=False)
        if cloud.returncode:
            raise RuntimeError("Operator credential unavailable; output suppressed")
        req = urllib.request.Request(
            "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/" + options.google_service_account + ":generateAccessToken",
            # GKE needs userinfo.email to identify the IAM account by email.
            data=json.dumps({"scope": ["https://www.googleapis.com/auth/cloud-platform",
                                       "https://www.googleapis.com/auth/userinfo.email"], "lifetime": "900s"}).encode(),
            headers={"Authorization": "Bearer " + cloud.stdout.strip(), "Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                credential = json.load(response)
        except urllib.error.HTTPError as error:
            code = error.code
            error.close()
            raise RuntimeError(f"Google service account impersonation failed: HTTP {code}") from None
        token = credential["accessToken"]
        expires_at = credential["expireTime"]
        subject = options.google_service_account
        credential_source = "operator-impersonation"
    else:
        token = kubectl(options.kubeconfig, "create", "token", "argocd-deployer", "-n", "sample-app", "--duration=15m")
        token_payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(token_payload + "=" * (-len(token_payload) % 4)))
        expires_at = dt.datetime.fromtimestamp(claims["exp"], dt.timezone.utc).isoformat()
        subject = "system:serviceaccount:sample-app:argocd-deployer"
        credential_source = "kubernetes-tokenrequest"
    results = []

    def request(label, method, path, expected, body=None, read_body=False, content_type="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            target["server"] + path, data=data, method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": content_type},
        )
        response_body = None
        try:
            with urllib.request.urlopen(req, context=context, timeout=20) as response:
                status = response.status
                if read_body:
                    response_body = json.load(response)
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
        if status != expected:
            raise RuntimeError(f"{label}: expected HTTP {expected}, received {status}")
        results.append({"check": label, "httpStatus": status, "passed": True})
        return response_body

    request("read own namespace pods", "GET", "/api/v1/namespaces/sample-app/pods", 200)
    request("read own namespace rollouts", "GET", "/apis/argoproj.io/v1alpha1/namespaces/sample-app/rollouts", 200)
    expected_sa_uid = kubectl(options.kubeconfig, "get", "serviceaccount", "argocd-deployer", "-n", "sample-app", "-o", "jsonpath={.metadata.uid}")
    sa = request("read target service account identity", "GET", "/api/v1/namespaces/sample-app/serviceaccounts/argocd-deployer", 200, read_body=True)
    if sa["metadata"]["uid"] != expected_sa_uid:
        raise RuntimeError("Deployer service account UID mismatch")
    request("deny kube-system pods", "GET", "/api/v1/namespaces/kube-system/pods", 403)
    request("deny cluster nodes", "GET", "/api/v1/nodes", 403)
    request("deny token issuance", "POST", "/api/v1/namespaces/sample-app/serviceaccounts/argocd-deployer/token", 403,
            {"apiVersion": "authentication.k8s.io/v1", "kind": "TokenRequest", "spec": {"audiences": ["https://kubernetes.default.svc"], "expirationSeconds": 600}})
    request("deny secret writes", "POST", "/api/v1/namespaces/sample-app/secrets?dryRun=All", 403,
            {"apiVersion": "v1", "kind": "Secret", "metadata": {"name": "rbac-check", "namespace": "sample-app"}})
    request("deny RBAC escalation", "POST", "/apis/rbac.authorization.k8s.io/v1/namespaces/sample-app/rolebindings?dryRun=All", 403,
            {"apiVersion": "rbac.authorization.k8s.io/v1", "kind": "RoleBinding", "metadata": {"name": "rbac-check", "namespace": "sample-app"},
             "roleRef": {"apiGroup": "rbac.authorization.k8s.io", "kind": "ClusterRole", "name": "cluster-admin"},
             "subjects": [{"kind": "ServiceAccount", "name": "argocd-deployer", "namespace": "sample-app"}]})

    if options.google_service_account:
        # Check all Argo CD write verbs with the real Google identity, without writes.
        permissions = [(group, resource, verb, "sample-app", True)
                       for group, resource in (("", "services"), ("argoproj.io", "rollouts"), ("argoproj.io", "analysistemplates"))
                       for verb in ("create", "update", "patch", "delete")]
        permissions += [("", "namespaces", "create", "", False),
                        ("rbac.authorization.k8s.io", "clusterroles", "create", "", False),
                        ("", "secrets", "patch", "sample-app", False)]
        for group, resource, verb, namespace, allowed in permissions:
            review = request("self permission " + verb + " " + resource, "POST",
                             "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", 201,
                             {"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview",
                              "spec": {"resourceAttributes": {"group": group, "resource": resource, "verb": verb, "namespace": namespace}}},
                             read_body=True)
            if review["status"].get("allowed", False) != allowed:
                raise RuntimeError(f"Unexpected permission: {verb} {resource}")
            results[-1].update(allowed=review["status"].get("allowed", False), expectedAllowed=allowed)

    # Both RoleBindings must support manual promotion without expanding other writes.
    status_permissions = [("argoproj.io", "rollouts", verb, "sample-app", True)
                          for verb in ("get", "patch", "update")]
    status_permissions += [("argoproj.io", "rollouts", "patch", "kube-system", False),
                           ("apps", "deployments", "patch", "sample-app", False)]
    for group, resource, verb, namespace, allowed in status_permissions:
        label = f"self permission {namespace} {verb} {resource}/status"
        review = request(label, "POST", "/apis/authorization.k8s.io/v1/selfsubjectaccessreviews", 201,
                         {"apiVersion": "authorization.k8s.io/v1", "kind": "SelfSubjectAccessReview",
                          "spec": {"resourceAttributes": {"group": group, "resource": resource,
                                   "subresource": "status", "verb": verb, "namespace": namespace,
                                   "name": "sample-app"}}}, read_body=True)
        if review["status"].get("allowed", False) != allowed:
            raise RuntimeError(f"Unexpected permission: {namespace} {verb} {resource}/status")
        results[-1].update(allowed=review["status"].get("allowed", False), expectedAllowed=allowed)

    if options.verify_rollout_status:
        status_path = "/apis/argoproj.io/v1alpha1/namespaces/sample-app/rollouts/sample-app/status"
        request("read existing Rollout status", "GET", status_path, 200)
        request("server dry-run patch existing Rollout status", "PATCH", status_path + "?dryRun=All", 200,
                {}, content_type="application/merge-patch+json")

    rendered_resources = []
    if options.rendered_overlay:
        import yaml
        resources = {
            ("v1", "Service"): "/api/v1/namespaces/sample-app/services",
            ("argoproj.io/v1alpha1", "Rollout"): "/apis/argoproj.io/v1alpha1/namespaces/sample-app/rollouts",
            ("argoproj.io/v1alpha1", "AnalysisTemplate"): "/apis/argoproj.io/v1alpha1/namespaces/sample-app/analysistemplates",
        }
        documents = [d for d in yaml.safe_load_all(Path(options.rendered_overlay).read_text(encoding="utf-8")) if d]
        identities = [(d["apiVersion"], d["kind"], d["metadata"]["name"]) for d in documents]
        if len(identities) != len(set(identities)):
            raise RuntimeError("Duplicate resources in combined Application sources")
        services = {d["metadata"]["name"] for d in documents if d["kind"] == "Service"}
        rollouts = [d for d in documents if d["kind"] == "Rollout"]
        analyses = [d for d in documents if d["kind"] == "AnalysisTemplate"]
        if len(rollouts) != 1 or len(analyses) != 1 or len(services) not in (1, 2) or len(documents) != len(services) + 2:
            raise RuntimeError("Expected DB-free GCP Service(s), one Rollout and one AnalysisTemplate")
        blue_green = rollouts[0]["spec"]["strategy"].get("blueGreen")
        if blue_green and services != {blue_green["activeService"], blue_green["previewService"]}:
            raise RuntimeError("BlueGreen active/preview Service references do not match combined manifests")
        for document in documents:
            key = (document["apiVersion"], document["kind"])
            if key not in resources or document["metadata"].get("namespace") != "sample-app":
                raise RuntimeError("Unexpected overlay resource or namespace")
            original_name = document["metadata"]["name"]
            rendered_resources.append({"apiVersion": key[0], "kind": key[1], "name": original_name, "namespace": "sample-app"})
            document["metadata"]["name"] += "-rbac-check"
            request("server dry-run create " + key[1] + "/" + original_name, "POST", resources[key] + "?dryRun=All", 201, document)

    # Credential material and API response bodies are deliberately excluded.
    report = {
        "verifiedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": target,
        "rollouts": {"image": container["image"], "availableReplicas": 1, "resources": container["resources"], "establishedCrds": established},
        "rbacSubject": subject,
        "deployerServiceAccountUid": expected_sa_uid,
        "credentialSource": credential_source,
        "temporaryTokenExpiresAtUtc": expires_at,
        "checks": results,
        "renderedResources": rendered_resources,
        "appResourcesCreated": False,
        "rolloutStatusDryRunVerified": options.verify_rollout_status,
        "rolloutPromoted": False,
        "eksRegistrationVerified": False,
        "eksWifExchangeVerified": False,
    }
    Path(options.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: Rollouts, {len(established)} CRDs and {len(results)} authenticated RBAC checks")
    print("App resource writes were server dry-run; EKS registration is not verified.")


if __name__ == "__main__":
    main()
