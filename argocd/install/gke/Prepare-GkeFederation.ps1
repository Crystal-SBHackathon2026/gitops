param(
    [Parameter(Mandatory = $true)][string]$KubeconfigPath,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$KubeconfigPath = (Resolve-Path -LiteralPath $KubeconfigPath).Path
$target = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'target.json') -Raw | ConvertFrom-Json
$federation = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'federation.json') -Raw | ConvertFrom-Json
function Invoke-Gcp {
    param([string[]]$Arguments)
    $output = & gcloud @Arguments --project=$($target.project) --quiet --format=json
    if ($LASTEXITCODE -ne 0) { throw ('gcloud failed: ' + ($Arguments[0..1] -join ' ')) }
    if ($output) { return ($output -join "`n") | ConvertFrom-Json }
}
$project = Invoke-Gcp -Arguments @('projects', 'describe', $target.project)
if ([string]$project.projectNumber -ne $federation.projectNumber) { throw 'Project number mismatch; no changes applied.' }
$cluster = Invoke-Gcp -Arguments @('container', 'clusters', 'describe', $target.cluster, '--zone', $target.zone)
$config = & kubectl --kubeconfig $KubeconfigPath config view --minify -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $config.clusters[0].cluster.server.TrimEnd('/') -ne $target.server -or ('https://' + $cluster.endpoint) -ne $target.server) {
    throw 'GKE API mismatch; no changes applied.'
}
$namespaceRaw = & kubectl --kubeconfig $KubeconfigPath --request-timeout=15s get --raw /api/v1/namespaces/kube-system
if ($LASTEXITCODE -ne 0) { throw 'GKE UID read failed; no changes applied.' }
$uid = ($namespaceRaw | ConvertFrom-Json).metadata.uid
if ($uid -ne $target.kubeSystemUid) { throw 'GKE UID mismatch; no changes applied.' }
if (-not $cluster.masterAuthorizedNetworksConfig.enabled -or $cluster.masterAuthorizedNetworksConfig.gcpPublicCidrsAccessEnabled) {
    throw 'Unexpected API access policy; review before changing it.'
}
$originalCidrs = @($cluster.masterAuthorizedNetworksConfig.cidrBlocks | ForEach-Object { $_.cidrBlock })
$desiredCidrs = @($originalCidrs + $federation.eksEgressCidr | Select-Object -Unique)
if ($desiredCidrs -contains '0.0.0.0/0') { throw 'Internet-wide API access is not permitted.' }
$condition = "assertion.sub in ['" + ($federation.subjects -join "', '") + "']"
$members = @($federation.subjects | ForEach-Object {
    'principal://iam.googleapis.com/projects/' + $federation.projectNumber + '/locations/global/workloadIdentityPools/' + $federation.poolId + '/subject/' + $_
})
$pools = @(Invoke-Gcp -Arguments @('iam', 'workload-identity-pools', 'list', '--location=global'))
$pool = @($pools | Where-Object { ($_.name -split '/')[-1] -eq $federation.poolId })
if ($pool.Count -and $pool[0].state -ne 'ACTIVE') { throw 'Existing WIF pool is not active.' }
$providers = @()
if ($pool.Count) {
    $providers = @(Invoke-Gcp -Arguments @('iam', 'workload-identity-pools', 'providers', 'list', '--location=global', '--workload-identity-pool', $federation.poolId))
}
$provider = @($providers | Where-Object { ($_.name -split '/')[-1] -eq $federation.providerId })
if (@($providers | Where-Object { ($_.name -split '/')[-1] -ne $federation.providerId }).Count) {
    throw 'Unexpected provider in this dedicated pool; review trust before applying.'
}
if ($provider.Count -and ($provider[0].state -ne 'ACTIVE' -or $provider[0].disabled -or $provider[0].oidc.issuerUri -ne $federation.issuer -or
    $provider[0].attributeMapping.'google.subject' -ne 'assertion.sub' -or $provider[0].attributeCondition -ne $condition -or $provider[0].oidc.allowedAudiences.Count)) {
    throw 'Existing WIF provider differs from the agreed trust policy.'
}
$accounts = @(Invoke-Gcp -Arguments @('iam', 'service-accounts', 'list'))
$account = @($accounts | Where-Object { $_.email -eq $federation.serviceAccountEmail })
if ($account.Count -and $account[0].disabled) { throw 'Existing Google service account is disabled.' }
if ($account.Count) {
    $policy = Invoke-Gcp -Arguments @('iam', 'service-accounts', 'get-iam-policy', $federation.serviceAccountEmail)
    foreach ($binding in $policy.bindings) {
        if ($binding.role -ne 'roles/iam.workloadIdentityUser' -or $binding.condition -or @($binding.members | Where-Object { $_ -notin $members }).Count) {
            throw 'Existing service account IAM differs from the narrow agreed policy.'
        }
    }
}
if ($PlanOnly) {
    [pscustomobject]@{ projectNumber=$federation.projectNumber; poolExists=($pool.Count -gt 0); providerExists=($provider.Count -gt 0);
        serviceAccountExists=($account.Count -gt 0); originalCidrs=$originalCidrs; desiredCidrs=$desiredCidrs; changesApplied=$false } | ConvertTo-Json
    return
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$OutputDirectory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$operation = $null
if (@($desiredCidrs | Where-Object { $_ -notin $originalCidrs }).Count) {
    $operation = Invoke-Gcp -Arguments @('container', 'clusters', 'update', $target.cluster, '--zone', $target.zone,
        '--enable-master-authorized-networks', ('--master-authorized-networks=' + ($desiredCidrs -join ',')), '--async')
}
Invoke-Gcp -Arguments @('services', 'enable', 'iam.googleapis.com', 'iamcredentials.googleapis.com', 'cloudresourcemanager.googleapis.com', 'sts.googleapis.com') | Out-Null
if (-not $pool.Count) {
    Invoke-Gcp -Arguments @('iam', 'workload-identity-pools', 'create', $federation.poolId, '--location=global', '--display-name=Crystal EKS Argo CD') | Out-Null
}
if (-not $provider.Count) {
    Invoke-Gcp -Arguments @('iam', 'workload-identity-pools', 'providers', 'create-oidc', $federation.providerId, '--location=global',
        '--workload-identity-pool', $federation.poolId, '--issuer-uri', $federation.issuer,
        '--attribute-mapping=google.subject=assertion.sub', '--attribute-condition', $condition) | Out-Null
}
if (-not $account.Count) {
    Invoke-Gcp -Arguments @('iam', 'service-accounts', 'create', $federation.serviceAccountId, '--display-name=Argo CD Tokyo deployer') | Out-Null
}
foreach ($member in $members) {
    Invoke-Gcp -Arguments @('iam', 'service-accounts', 'add-iam-policy-binding', $federation.serviceAccountEmail,
        '--role=roles/iam.workloadIdentityUser', ('--member=' + $member), '--condition=None') | Out-Null
}
& kubectl --kubeconfig $KubeconfigPath --request-timeout=30s apply --server-side --field-manager=crystal-gke-bootstrap -f (Join-Path $PSScriptRoot 'google-deployer-rolebinding.yaml')
if ($LASTEXITCODE -ne 0) { throw 'Google deployer RoleBinding apply failed.' }
$report = [ordered]@{ preparedAtUtc=[DateTime]::UtcNow.ToString('o'); projectNumber=$federation.projectNumber; poolId=$federation.poolId;
    providerId=$federation.providerId; serviceAccountEmail=$federation.serviceAccountEmail; originalCidrs=$originalCidrs; desiredCidrs=$desiredCidrs;
    gkeNetworkOperation=$operation.name; eksResourcesChanged=$false; eksWifExchangeVerified=$false }
[IO.File]::WriteAllText((Join-Path $OutputDirectory 'federation-preparation.json'), ($report | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
$report | ConvertTo-Json
