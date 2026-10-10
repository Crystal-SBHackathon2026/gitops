"""Validate public definitions; --live reads EKS and submits server dry-runs only."""
import argparse
import base64
import copy
import datetime as dt
import hashlib
import json
import ssl
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
WORKLOADS = (
    ("controller", "statefulset", "argocd-application-controller"),
    ("server", "deployment", "argocd-server"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ca_hash(pem):
    return hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest()


def public_registration(value):
    """Decode only this public registration, without displaying Secret contents."""
    require(value["kind"] == "Secret" and value["type"] == "Opaque", "Unexpected registration type")
    require(value["metadata"]["name"] == "cluster-tokyo-gke" and value["metadata"]["namespace"] == "argocd", "Unexpected registration identity")
    require(value["metadata"].get("labels", {}).get("argocd.argoproj.io/secret-type") == "cluster", "Missing cluster registration label")
    data = value.get("stringData")
    if data is None:
        data = {key: base64.b64decode(raw, validate=True).decode("utf-8") for key, raw in value.get("data", {}).items()}
    require(set(data) == {"name", "server", "namespaces", "clusterResources", "config"}, "Unexpected registration field; raw output suppressed")
    return {**data, "config": json.loads(data["config"])}


def public_configmap(value):
    require(value["kind"] == "ConfigMap" and value["metadata"]["name"] == "tokyo-gke-wif" and value["metadata"]["namespace"] == "argocd", "Unexpected WIF ConfigMap identity")
    require(set(value["data"]) == {"credential-configuration.json", "gke-ca.crt"}, "Unexpected WIF ConfigMap field")
    return {"adc": json.loads(value["data"]["credential-configuration.json"]), "ca": ca_hash(value["data"]["gke-ca.crt"])}


def validate_definitions(root=ROOT):
    target = json.loads((root / "target.json").read_text(encoding="utf-8"))
    documents = {name: yaml.safe_load((root / name).read_text(encoding="utf-8")) for name in (
        "wif-configmap.yaml", "cluster-tokyo-gke.yaml", "controller-wif.patch.yaml", "server-wif.patch.yaml",
    )}
    require(set(target) == {"project", "zone", "cluster", "server", "kubeSystemUidExpected", "caSha256Der", "clusterSecret", "namespaces", "clusterResources", "gkeOperatingPrincipal", "eksSubjects", "issuer", "measuredControllerAndServerEgressCidr", "providerResource", "projectedTokenAudience", "projectedTokenRequestedLifetimeSeconds", "googleAccessTokenLifetimeSeconds", "eksClusterArn", "eksApiServer", "gkeServiceAccountUidExpected", "argoCdVersion"}, "Unexpected target metadata field")
    for filename, fields, metadata_fields in (
        ("wif-configmap.yaml", {"apiVersion", "kind", "metadata", "data"}, {"name", "namespace"}),
        ("cluster-tokyo-gke.yaml", {"apiVersion", "kind", "metadata", "type", "stringData"}, {"name", "namespace", "labels"}),
    ):
        require(set(documents[filename]) == fields and set(documents[filename]["metadata"]) == metadata_fields, "Unexpected manifest field; public definitions only")
        require(documents[filename]["apiVersion"] == "v1", "Unexpected API version")
    require(documents["cluster-tokyo-gke.yaml"]["metadata"]["labels"] == {"argocd.argoproj.io/secret-type": "cluster"}, "Unexpected registration label")
    cm = public_configmap(documents["wif-configmap.yaml"])
    expected_adc = {
        "type": "external_account",
        "audience": "//iam.googleapis.com/" + target["providerResource"],
        "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
        "token_url": "https://sts.googleapis.com/v1/token",
        "service_account_impersonation_url": "https://iamcredentials.googleapis.com/v1/projects/-/serviceAccounts/" + target["gkeOperatingPrincipal"] + ":generateAccessToken",
        "service_account_impersonation": {"token_lifetime_seconds": 3600},
        "credential_source": {"file": "/var/run/crystal-gcp-wif/token", "format": {"type": "text"}},
    }
    require(cm["adc"] == expected_adc, "ADC must use the reviewed projected JWT and dedicated service account only")
    require(cm["ca"] == target["caSha256Der"], "GKE CA fingerprint mismatch")
    registration = public_registration(documents["cluster-tokyo-gke.yaml"])
    require(registration == {
        "name": "tokyo-gke", "server": target["server"], "namespaces": "sample-app", "clusterResources": "false",
        "config": {
            "execProviderConfig": {"command": "argocd-k8s-auth", "args": ["gcp"], "apiVersion": "client.authentication.k8s.io/v1beta1", "env": {"GOOGLE_APPLICATION_CREDENTIALS": "/etc/crystal-gcp-wif/credential-configuration.json"}},
            "tlsClientConfig": {"insecure": False, "caData": base64.b64encode(documents["wif-configmap.yaml"]["data"]["gke-ca.crt"].encode("ascii")).decode("ascii")},
        },
    }, "Registration must retain TLS, exec-only authentication and sample-app scope")
    require(target["projectedTokenAudience"] == "https://iam.googleapis.com/" + target["providerResource"], "JWT/ADC audience mismatch")
    require(target["namespaces"] == ["sample-app"] and target["clusterResources"] is False, "Unexpected target management scope")
    require(target["cluster"] == "tokyo-gke" and target["clusterSecret"] == "cluster-tokyo-gke", "Unexpected target identity")
    require(target["projectedTokenRequestedLifetimeSeconds"] == target["googleAccessTokenLifetimeSeconds"] == 3600, "Unexpected token lifetime")
    require(target["eksSubjects"] == ["system:serviceaccount:argocd:" + name for _, _, name in WORKLOADS], "Unexpected WIF service account subjects")
    for label, _, name in WORKLOADS:
        expected_pod_patch = {
            "containers": [{"name": name, "volumeMounts": [
                {"name": "tokyo-gke-wif-token", "mountPath": "/var/run/crystal-gcp-wif", "readOnly": True},
                {"name": "tokyo-gke-wif-config", "mountPath": "/etc/crystal-gcp-wif", "readOnly": True},
            ]}],
            "volumes": [
                {"name": "tokyo-gke-wif-token", "projected": {"defaultMode": 420, "sources": [{"serviceAccountToken": {"audience": target["projectedTokenAudience"], "expirationSeconds": 3600, "path": "token"}}]}},
                {"name": "tokyo-gke-wif-config", "configMap": {"name": "tokyo-gke-wif", "defaultMode": 420}},
            ],
        }
        require(documents[f"{label}-wif.patch.yaml"] == {"spec": {"template": {"spec": expected_pod_patch}}}, "Patch must contain only reviewed WIF mounts/volumes")
    return target, documents


def check_live(args, target, documents):
    base = ["kubectl", "--context", args.context, "--request-timeout=30s"]
    if args.kubeconfig:
        base += ["--kubeconfig", str(args.kubeconfig)]

    def run(arguments):
        result = subprocess.run(base + arguments + ["-o", "json"], capture_output=True, text=True, encoding="utf-8", timeout=60)
        require(result.returncode == 0, "kubectl read/dry-run failed; raw output suppressed. Check context, login and connectivity.")
        return json.loads(result.stdout)

    config = run(["config", "view", "--minify"])
    require(config["clusters"][0]["cluster"]["server"] == target["eksApiServer"], "Selected context is not the recorded EKS oneaction API")
    require(not config["clusters"][0]["cluster"].get("insecure-skip-tls-verify", False), "EKS TLS verification must remain enabled")
    get = lambda kind, name: run(["-n", "argocd", "get", kind, name])
    cm_before = public_configmap(get("configmap", "tokyo-gke-wif"))
    secret_before = public_registration(get("secret", "cluster-tokyo-gke"))
    require(cm_before == public_configmap(documents["wif-configmap.yaml"]), "Live WIF public configuration differs")
    require(secret_before == public_registration(documents["cluster-tokyo-gke.yaml"]), "Live public registration differs")
    workloads = {(kind, name): get(kind, name) for _, kind, name in WORKLOADS}
    apps_before = {v["metadata"]["name"]: v["spec"] for v in run(["-n", "argocd", "get", "applications"])["items"]}
    selector = "app.kubernetes.io/name in (argocd-application-controller,argocd-server)"
    pods = lambda: {v["metadata"]["uid"] for v in run(["-n", "argocd", "get", "pods", "-l", selector])["items"]}
    pods_before = pods()
    require(len(pods_before) >= 2, "Expected Argo CD Controller/server Pods are absent")
    for label, kind, name in WORKLOADS:
        before = workloads[(kind, name)]
        pod = before["spec"]["template"]["spec"]
        require(pod["serviceAccountName"] == name, "Workload service account differs from WIF subjects")
        container = next(v for v in pod["containers"] if v["name"] == name)
        require(container["image"] == "quay.io/argoproj/argocd:" + target["argoCdVersion"], "Argo CD version differs; review authentication compatibility")
        desired = documents[f"{label}-wif.patch.yaml"]["spec"]["template"]["spec"]
        require([v for v in container.get("volumeMounts", []) if v["name"].startswith("tokyo-gke-wif-")] == desired["containers"][0]["volumeMounts"], "Live WIF mounts differ")
        actual_volumes = copy.deepcopy([v for v in pod["volumes"] if v["name"].startswith("tokyo-gke-wif-")])
        for volume in actual_volumes:
            if volume.get("configMap", {}).get("optional") is False:
                del volume["configMap"]["optional"]
        require(actual_volumes == desired["volumes"], "Live WIF volumes differ")
        require(before.get("status", {}).get("readyReplicas", 0) == before["spec"].get("replicas", 1) > 0, "Argo CD workload is not Ready")
        after = run(["-n", "argocd", "patch", kind, name, "--type=strategic", "--dry-run=server", "--patch-file", str(ROOT / f"{label}-wif.patch.yaml")])
        require(after["spec"] == before["spec"], "Dry-run would change current workload spec; inspect drift before applying")
    for filename, extract, before in (
        ("wif-configmap.yaml", public_configmap, cm_before),
        ("cluster-tokyo-gke.yaml", public_registration, secret_before),
    ):
        after = run(["-n", "argocd", "apply", "--dry-run=server", "-f", str(ROOT / filename)])
        require(extract(after) == before, "Dry-run changes current public registration/configuration")
    require(all(get(kind, name)["spec"] == value["spec"] for (kind, name), value in workloads.items()), "Concurrent workload spec change; repeat verification")
    require(pods() == pods_before, "Argo CD Pod set changed during verification")
    require(public_configmap(get("configmap", "tokyo-gke-wif")) == cm_before and public_registration(get("secret", "cluster-tokyo-gke")) == secret_before, "Concurrent WIF configuration change")
    require({v["metadata"]["name"]: v["spec"] for v in run(["-n", "argocd", "get", "applications"])["items"]} == apps_before, "Concurrent Application spec change; repeat verification")
    return {"livePublicConfigurationMatches": True, "serverDryRunsPassed": 4, "workloadSpecsUnchanged": True, "argoPodUidsUnchanged": True, "applicationSpecsUnchanged": True, "applicationHealthNotEvaluated": True, "gkeAuthenticationNotRepeated": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Read EKS and perform server dry-runs; never apply")
    parser.add_argument("--context", help="Explicit EKS context; required with --live")
    parser.add_argument("--kubeconfig", type=Path)
    parser.add_argument("--report", type=Path, help="Write a public summary only")
    args = parser.parse_args()
    if args.live and not args.context:
        parser.error("--live requires an explicit --context")
    target, documents = validate_definitions()
    report = {"verifiedAtUtc": dt.datetime.now(dt.timezone.utc).isoformat(), "publicDefinitionsValidated": True, "liveChecked": args.live, "resourcesApplied": False, "podsRestarted": False}
    if args.live:
        report.update(check_live(args, target, documents))
    report["verifiedAtUtc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
