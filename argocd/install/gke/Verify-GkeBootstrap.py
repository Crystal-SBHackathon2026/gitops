"""GKE target, Rollouts and namespace RBAC verification; no EKS changes.

A 15-minute TokenRequest credential stays in memory. App writes use server dry-run.
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
    parser.add_argument("--rendered-overlay")
    parser.add_argument("--output", required=True)
    options = parser.parse_args()
    target = json.loads(Path(__file__).with_name("target.json").read_text(encoding="utf-8"))
    config = json.loads(kubectl(options.kubeconfig, "config", "view", "--minify", "--raw", "-o", "json"))
    cluster = config["clusters"][0]["cluster"]
    if cluster["server"].rstrip("/") != target["server"]:
        raise RuntimeError("GKE API address mismatch")
    uid = kubectl(options.kubeconfig, "get", "namespace", "kube-system", "-o", "jsonpath={.metadata.uid}")
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
    token = kubectl(options.kubeconfig, "create", "token", "argocd-deployer", "-n", "sample-app", "--duration=15m")
    token_payload = token.split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(token_payload + "=" * (-len(token_payload) % 4)))
    results = []

    def request(label, method, path, expected, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            target["server"] + path, data=data, method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, context=context, timeout=20) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
            error.close()
        if status != expected:
            raise RuntimeError(f"{label}: expected HTTP {expected}, received {status}")
        results.append({"check": label, "httpStatus": status, "passed": True})

    request("read own namespace pods", "GET", "/api/v1/namespaces/sample-app/pods", 200)
    request("read own namespace rollouts", "GET", "/apis/argoproj.io/v1alpha1/namespaces/sample-app/rollouts", 200)
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

    if options.rendered_overlay:
        import yaml
        resources = {
            ("v1", "Service"): "/api/v1/namespaces/sample-app/services",
            ("argoproj.io/v1alpha1", "Rollout"): "/apis/argoproj.io/v1alpha1/namespaces/sample-app/rollouts",
            ("argoproj.io/v1alpha1", "AnalysisTemplate"): "/apis/argoproj.io/v1alpha1/namespaces/sample-app/analysistemplates",
        }
        documents = list(yaml.safe_load_all(Path(options.rendered_overlay).read_text(encoding="utf-8")))
        if len(documents) != 3:
            raise RuntimeError("Expected the current DB-free GCP overlay's three resources")
        for document in documents:
            key = (document["apiVersion"], document["kind"])
            if key not in resources or document["metadata"].get("namespace") != "sample-app":
                raise RuntimeError("Unexpected overlay resource or namespace")
            document["metadata"]["name"] += "-rbac-check"
            request("server dry-run create " + key[1], "POST", resources[key] + "?dryRun=All", 201, document)

    # Credential material and API response bodies are deliberately excluded.
    report = {
        "verifiedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "target": target,
        "rollouts": {"image": container["image"], "availableReplicas": 1, "resources": container["resources"], "establishedCrds": established},
        "rbacSubject": "system:serviceaccount:sample-app:argocd-deployer",
        "temporaryTokenExpiresAtUtc": dt.datetime.fromtimestamp(claims["exp"], dt.timezone.utc).isoformat(),
        "checks": results,
        "appResourcesCreated": False,
        "eksRegistrationVerified": False,
    }
    Path(options.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: Rollouts, {len(established)} CRDs and {len(results)} authenticated RBAC checks")
    print("App resource writes were server dry-run; EKS registration is not verified.")


if __name__ == "__main__":
    main()
