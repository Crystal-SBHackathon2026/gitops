param(
    [Parameter(Mandatory = $true)]
    [string]$KubeconfigPath,
    [Parameter(Mandatory = $true)]
    [string]$ArtifactDirectory,
    [string]$ExpectedKubeSystemUid,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$KubeconfigPath = (Resolve-Path -LiteralPath $KubeconfigPath).Path
$target = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'target.json') -Raw | ConvertFrom-Json
$source = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'rollouts-source.json') -Raw | ConvertFrom-Json
if (-not $ExpectedKubeSystemUid) { $ExpectedKubeSystemUid = $target.kubeSystemUid }

function Invoke-GkeKubectl {
    param([string[]]$KubectlArguments)
    $commandOutput = & kubectl --kubeconfig $KubeconfigPath --request-timeout=30s @KubectlArguments
    if ($LASTEXITCODE -ne 0) {
        throw ('kubectl failed: ' + ($KubectlArguments -join ' '))
    }
    return $commandOutput
}

# Every Kubernetes call uses this separate kubeconfig. Never switch the default context.
$clusterConfig = (Invoke-GkeKubectl -KubectlArguments @('config', 'view', '--minify', '-o', 'json')) | ConvertFrom-Json
if ($clusterConfig.clusters[0].cluster.server.TrimEnd('/') -ne $target.server) {
    throw 'GKE API address mismatch; no changes applied.'
}
$actualUid = (Invoke-GkeKubectl -KubectlArguments @('get', 'namespace', 'kube-system', '-o', 'jsonpath={.metadata.uid}')).Trim()
if ($actualUid -ne $ExpectedKubeSystemUid) {
    throw 'GKE kube-system UID mismatch; no changes applied.'
}
foreach ($resource in @('customresourcedefinitions.apiextensions.k8s.io', 'clusterroles.rbac.authorization.k8s.io')) {
    $allowed = (Invoke-GkeKubectl -KubectlArguments @('auth', 'can-i', 'create', $resource)).Trim()
    if ($allowed -ne 'yes') { throw ('Missing bootstrap permission: ' + $resource) }
}
$existingDeployment = Invoke-GkeKubectl -KubectlArguments @('get', 'deployment', 'argo-rollouts', '-n', 'argo-rollouts', '--ignore-not-found', '-o', 'json')
if ($existingDeployment) {
    $existingImage = ($existingDeployment | ConvertFrom-Json).spec.template.spec.containers[0].image
    if ($existingImage -ne ('quay.io/argoproj/argo-rollouts:' + $source.version)) {
        throw 'A different Rollouts version exists; review upgrade ownership before applying.'
    }
}

New-Item -ItemType Directory -Path $ArtifactDirectory -Force | Out-Null
$ArtifactDirectory = (Resolve-Path -LiteralPath $ArtifactDirectory).Path
$manifestPath = Join-Path $ArtifactDirectory 'upstream.yaml'
if (-not (Test-Path -LiteralPath $manifestPath)) {
    Invoke-WebRequest -Uri $source.url -OutFile $manifestPath
}
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($manifestHash -ne $source.sha256) { throw 'Rollouts source checksum mismatch; no changes applied.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'controller-resources.patch.yaml') -Destination (Join-Path $ArtifactDirectory 'controller-resources.patch.yaml') -Force
$renderConfig = @'
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: argo-rollouts
resources:
  - upstream.yaml
patches:
  - path: controller-resources.patch.yaml
'@
[IO.File]::WriteAllText((Join-Path $ArtifactDirectory 'kustomization.yaml'), $renderConfig, [Text.UTF8Encoding]::new($false))

if ($ValidateOnly) {
    Invoke-GkeKubectl -KubectlArguments @('apply', '--dry-run=client', '--validate=false', '-k', $PSScriptRoot)
    Invoke-GkeKubectl -KubectlArguments @('apply', '--dry-run=client', '--validate=false', '-k', $ArtifactDirectory)
    Write-Output ('Validated target ' + $target.cluster + '; no changes applied.')
    return
}

Invoke-GkeKubectl -KubectlArguments @('apply', '--server-side', '--field-manager=crystal-gke-bootstrap', '-f', (Join-Path $PSScriptRoot 'namespaces.yaml'))
Invoke-GkeKubectl -KubectlArguments @('apply', '--server-side', '--field-manager=crystal-gke-bootstrap', '-k', $ArtifactDirectory)
foreach ($crd in @('rollouts', 'analysistemplates', 'analysisruns', 'experiments', 'clusteranalysistemplates')) {
    Invoke-GkeKubectl -KubectlArguments @('wait', '--for=condition=Established', ('crd/' + $crd + '.argoproj.io'), '--timeout=90s')
}
Invoke-GkeKubectl -KubectlArguments @('apply', '--server-side', '--field-manager=crystal-gke-bootstrap', '-f', (Join-Path $PSScriptRoot 'rbac.yaml'))
Invoke-GkeKubectl -KubectlArguments @('rollout', 'status', 'deployment/argo-rollouts', '-n', 'argo-rollouts', '--timeout=180s')
Write-Output ('Bootstrap ready on ' + $target.cluster + '. EKS registration and app sync remain separate steps.')
