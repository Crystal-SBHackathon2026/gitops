# 중앙 EKS Argo CD → GKE 인증·등록

이미 운영 중인 `oneaction`의 `tokyo-gke` 인증과 등록을 재현하는 공개 정의예요. 2026-10-10 16:43 KST 등록과 17:42 KST 실제 만료 후 재발급 검증을 완료했어요. [EKS 검증 기록](../../../docs/eks-gke-registration-verification-2026-10-10.md)에 완료 범위와 남은 검증을 구분했어요.

이 폴더는 중앙 EKS용이에요. GKE 설치·Google IAM·WIF provider·GKE RBAC는 [GKE 준비 절차](../gke/README.md)의 담당 범위예요. 여기 파일을 GKE나 로컬 k3s에 적용하지 않아요. 이 폴더를 동기화하는 Application은 추가하지 않았고, Git에 기록하는 것만으로 운영 리소스가 재적용되지는 않아요.

## 파일과 담당 범위

| 파일 | 용도 |
| --- | --- |
| [target.json](target.json) | EKS/GKE 대상, 공개 식별자·CA 지문·인증 주체 |
| [wif-configmap.yaml](wif-configmap.yaml) | 외부 계정 ADC와 공개 GKE CA |
| [controller-wif.patch.yaml](controller-wif.patch.yaml) | Controller의 WIF 마운트·projected JWT volume만 추가하는 strategic merge patch |
| [server-wif.patch.yaml](server-wif.patch.yaml) | server의 동일 패치 |
| [cluster-tokyo-gke.yaml](cluster-tokyo-gke.yaml) | Argo CD 클러스터 등록: 공개 접속 정보와 exec 인증 설정 |
| [Verify-EksGkeRegistration.py](Verify-EksGkeRegistration.py) | 정적 검증 또는 현재 EKS 비교·서버 dry-run. 실제 적용 명령은 실행하지 않음 |

등록 리소스는 Kubernetes `Secret`이지만 내용은 **공개 API 주소·CA·인증 명령·ADC 파일 경로**예요. bearer token, Google 서비스 계정 키, 개인 계정 인증값은 없어요. JWT는 kubelet이 Pod 안에 투영하고 Google access token은 실행 시 발급해요. 이 값과 exec 명령의 출력을 Git·로그·Slack에 저장하지 않아요.

| 담당 | 관리할 부분 |
| --- | --- |
| EKS | 이 폴더의 ConfigMap·Controller/server 마운트·등록 Secret, EKS 실행 경로 검증 |
| GCP | WIF provider 조건·계정 IAM·GKE API allowlist·namespace RBAC·GKE 대상 식별 |
| GitOps | 중앙 Application 적용 시점·sources·Notifications·앱 동기화 결과 |

Terraform이 관리하는 AWS 네트워크·IAM·EKS 자원을 이 폴더에서 다시 만들지 않아요. 별도 AWS IAM 권한이나 고정 Google 키를 추가하는 방식도 사용하지 않아요.

## 인증 흐름과 공개 값

1. EKS의 `argocd/argocd-application-controller`와 `argocd/argocd-server` SA에 대해 projected JWT를 요청해요.
2. `crystal-eks/oneaction` provider가 EKS issuer와 두 SA subject를 확인해 Google STS에서 교환해요.
3. 전용 Google 계정 `argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com`을 impersonate해요.
4. Argo CD v3.5.4의 공식 `argocd-k8s-auth gcp`가 ADC를 읽어 GKE 접속용 exec credential을 반환해요.
5. GKE의 이메일 `kind: User` RoleBinding과 제한된 Role이 `sample-app`의 관리 권한을 결정해요.

| 항목 | 값 |
| --- | --- |
| EKS | 계정 `236550433066`, `ap-northeast-2`, `oneaction` |
| GKE | `crystal-sbh2026-gcp-1009` / `asia-northeast1-a` / `tokyo-gke` |
| GKE API | `https://34.146.143.116` |
| EKS 실제 송신 CIDR | Controller/server 모두 `43.200.199.19/32` — 2026-10-10 실측 |
| 등록·관리 범위 | `tokyo-gke`, `namespaces=sample-app`, `clusterResources=false` |
| TLS | `insecure=false`, 등록 CA DER SHA256 `edc9b0643f0456a2e6e9cba6bb91a223acb0b6acca681e880cb7ea4f351b6a42` |
| JWT 요청 수명 / Google token 수명 | 각각 `3600`초 |
| JWT 파일 | `/var/run/crystal-gcp-wif/token` |
| ADC 파일 | `/etc/crystal-gcp-wif/credential-configuration.json` |

projected JWT audience는 `https://iam.googleapis.com/projects/19323760731/locations/global/workloadIdentityPools/crystal-eks/providers/oneaction`이고, ADC audience는 `//iam.googleapis.com/projects/19323760731/locations/global/workloadIdentityPools/crystal-eks/providers/oneaction`이에요. 두 표현을 서로 바꾸지 않아요.

`execProviderConfig.env`는 키/값 **map**이고 `GOOGLE_APPLICATION_CREDENTIALS`로 ADC 경로를 전달해요. 공식 v3.5.4 인증 명령이 요청하는 `cloud-platform`·`userinfo.email` scope를 사용해요. 이메일 scope를 빼면 GKE가 숫자 uniqueID로 식별해 이메일 RoleBinding과 맞지 않을 수 있어요.

## 현재 상태 확인 — 적용 없음

GitOps 저장소 루트에서 Python 3·PyYAML·kubectl을 사용해요. PyYAML이 없다면 사용하는 Python 환경에 `python -m pip install PyYAML`로 준비해요.

```powershell
python argocd/install/eks-gke/Verify-EksGkeRegistration.py
```

정적 검증은 공개 ADC·CA 일치, exec-only 등록, namespace 제한, WIF 마운트만 포함한 패치인지 확인해요. API에 접속하지 않아요.

운영 비교에는 팀 SSO 계정과 EKS API 접근이 가능한 PC가 필요해요. 팀 프로필 이름을 넣고 계정 번호를 확인한 뒤 별도 kubeconfig를 만들어요. 사람의 SSO 인증은 위 Pod의 Google WIF 인증과 별개예요.

```powershell
$ProfileName = '<팀-SSO-프로필>'
$ContextName = 'oneaction-gke-registration'
$KubeconfigPath = Join-Path $env:TEMP ('oneaction-gke-' + [guid]::NewGuid().ToString() + '.kubeconfig')
aws sso login --profile $ProfileName
if ($LASTEXITCODE -ne 0) { throw 'SSO login failed' }
$AccountId = aws sts get-caller-identity --profile $ProfileName --query Account --output text
if ($LASTEXITCODE -ne 0 -or $AccountId.Trim() -ne '236550433066') { throw 'Team account check failed' }
aws eks update-kubeconfig --profile $ProfileName --region ap-northeast-2 --name oneaction `
  --alias $ContextName --kubeconfig $KubeconfigPath
if ($LASTEXITCODE -ne 0) { throw 'kubeconfig creation failed' }

python argocd/install/eks-gke/Verify-EksGkeRegistration.py --live `
  --context $ContextName --kubeconfig $KubeconfigPath
```

`--live`는 대상 EKS API·TLS 설정을 확인한 다음 현재 공개 설정과 비교해요. ConfigMap·등록 Secret의 서버 apply dry-run 2개, Controller/server의 strategic patch dry-run 2개를 진행해요. 워크로드 spec·Pod UID·Application spec이 검사 중 유지됐는지도 확인해요. **실제 apply·patch·restart·GKE 토큰 발급은 하지 않아요.** 보고서를 저장하려면 Git 저장소 밖의 경로로 `--report <경로>`를 지정해요. 전체 Secret이나 토큰은 출력하지 않아요.

다른 팀원이 검사 중 Application을 수정하면 일치 검사에서 실패할 수 있어요. 운영 변경을 완료한 뒤 다시 검사하고, 실패를 임의로 무시해 적용하지 않아요. Application의 Healthy 판정이나 GCP 앱 배포 성공은 이 검사의 범위가 아니에요.

## 재설치·유실 복구 순서

**현재 정상 운영 중이면 이 절차를 실행할 필요가 없어요.** 같은 EKS에 Argo CD를 재설치하거나 이 인증 설정이 유실됐을 때 사용해요. WIF 마운트가 없던 Pod에 패치하면 Controller/server가 재시작되어 동기화·UI가 잠시 중단되므로 GitOps 담당과 적용 시간을 맞춰요.

1. [공통 설치 기록](../README.md)의 Argo CD v3.5.4를 준비해요. 기존 Argo CD의 인수·자원·replica·SA·probe·다른 volume은 유지해요.
2. 위 계정·kubeconfig 절차와 정적 검증을 진행해요. GCP 담당에게 현재 GKE API·CA·SA UID, provider issuer/두 subject, IAM·RBAC와 EKS 송신 CIDR 허용을 확인받아요.
3. 아래 각 dry-run을 먼저 확인하고 ConfigMap → server 마운트 → Controller 마운트 → 등록 Secret 순서로 복구해요. 명령은 위에서 만든 EKS kubeconfig를 명시해요.

```powershell
$InstallPath = 'argocd/install/eks-gke'
$KubectlArgs = @('--context', $ContextName, '--kubeconfig', $KubeconfigPath, '--request-timeout=30s', '-n', 'argocd')
function Invoke-EksKubectl {
  & kubectl @KubectlArgs @args
  if ($LASTEXITCODE -ne 0) { throw 'EKS operation failed; inspect before continuing' }
}

# EKS API와 TLS를 다시 확인한 뒤에만 복구해요.
$SelectedApi = & kubectl --context $ContextName --kubeconfig $KubeconfigPath config view --minify -o json
if ($LASTEXITCODE -ne 0) { throw 'Context read failed' }
$SelectedCluster = ($SelectedApi | ConvertFrom-Json).clusters[0].cluster
$RecordedTarget = Get-Content "$InstallPath/target.json" -Raw | ConvertFrom-Json
if ($SelectedCluster.server -ne $RecordedTarget.eksApiServer -or $SelectedCluster.'insecure-skip-tls-verify') {
  throw 'EKS API/TLS guard failed'
}

Invoke-EksKubectl apply --dry-run=server -f "$InstallPath/wif-configmap.yaml"
Invoke-EksKubectl apply -f "$InstallPath/wif-configmap.yaml"

Invoke-EksKubectl patch deployment argocd-server --type=strategic --dry-run=server `
  --patch-file "$InstallPath/server-wif.patch.yaml"
Invoke-EksKubectl patch deployment argocd-server --type=strategic `
  --patch-file "$InstallPath/server-wif.patch.yaml"
Invoke-EksKubectl rollout status deployment/argocd-server --timeout=300s

Invoke-EksKubectl patch statefulset argocd-application-controller --type=strategic --dry-run=server `
  --patch-file "$InstallPath/controller-wif.patch.yaml"
Invoke-EksKubectl patch statefulset argocd-application-controller --type=strategic `
  --patch-file "$InstallPath/controller-wif.patch.yaml"
Invoke-EksKubectl rollout status statefulset/argocd-application-controller --timeout=300s

Invoke-EksKubectl apply --dry-run=server -f "$InstallPath/cluster-tokyo-gke.yaml"
Invoke-EksKubectl apply -f "$InstallPath/cluster-tokyo-gke.yaml"

python argocd/install/eks-gke/Verify-EksGkeRegistration.py --live `
  --context $ContextName --kubeconfig $KubeconfigPath
if ($LASTEXITCODE -ne 0) { throw 'Registration verification failed' }
```

4. EKS 실제 실행 경로의 인증·대상 UID·권한 허용/거부를 다시 확인한 뒤 GitOps 담당이 GCP Application을 적용해요.

실제 재설치 후에는 4번의 인증 확인까지 필요해요. 정적 검증이나 dry-run만으로 Google STS·IAM·GKE RBAC의 현재 동작을 증명할 수는 없어요.

EKS나 GKE 자체를 재생성하면 endpoint·issuer·CA·UID가 바뀔 수 있어요. 이 파일을 그대로 재사용하지 않고 두 담당이 값을 다시 확인해 공개 정의와 WIF 조건을 함께 갱신해요. GKE CA는 공개 인증서지만 대상 확인 없이 교체하거나 `insecure=true`로 우회하지 않아요.

등록 철회가 필요한 경우 GitOps 담당과 GCP Application의 자동 동기화 중단을 먼저 맞춰요. 그 뒤 해당 등록 Secret과 이 이름의 마운트/volume만 제거하는 변경을 별도로 검토해요. 오래된 워크로드 전체 복원이나 `rollout undo`로 다른 팀원의 Argo CD 설정까지 되돌리지 않아요.

## 장애를 구분하는 기준

| 증상 | 먼저 확인할 부분 |
| --- | --- |
| GKE TCP timeout | 실제 Pod의 송신 CIDR, GKE API allowlist, NAT/route. 작업 PC IP와 구분 |
| JWT/STS 교환 실패 | EKS issuer, 두 SA subject, projected/ADC audience, JWT 파일 회전 |
| Google impersonation 실패 | 전용 계정의 WIF principal `roles/iam.workloadIdentityUser`, IAM Credentials API |
| TLS/CA 실패 | API 주소·CA 지문과 GCP 관리자 확인 결과 |
| GKE HTTP 403 | Google 이메일 identity·두 scope·`sample-app` RoleBinding. 다른 namespace 거부는 정상 |
| 재시작 후 인증 불가 | 해당 컨테이너의 두 read-only 마운트, ConfigMap·ADC 경로, 공식 exec 명령 |
| 장시간 동기화에서 만료 오류 | JWT 회전과 새 exec credential 발급을 구분하고 실제 Application의 갱신 경로 확인 |

토큰 교환을 진단할 때 exec 명령 출력을 터미널 로그나 파일에 남기지 않아요. 허용·거부와 대상 UID만 공개 결과로 전달해요.

## Application 연결과 남은 검증

[GCP 등록 인계](../../../docs/gcp-eks-registration-request.md)의 main Application을 사용해요. 목적지 `name: tokyo-gke`, `namespace: sample-app`과 overlay + `analysis/default` 두 source, 환경 표시·Notifications 구독·`CreateNamespace=false`를 유지해요. 이 작업에서는 Application이나 앱 overlay를 수정·적용하지 않아요.

양쪽 실제 Pod에서 최초 토큰 만료 후 새 exec credential을 발급받아 API 접근에 성공했어요. **실제 Application의 지속 동기화 중 client-go 자동 갱신**, GKE Pod·서비스·환경/버전·Notifications/baseline은 앱 적용 후 함께 확인할 항목이에요. 이 인증 기록의 완료를 앱 전체 배포 완료로 판단하지 않아요.

공식 근거: [Argo CD 선언적 클러스터 등록](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters), [v3.5.4 GCP 인증 명령](https://github.com/argoproj/argo-cd/blob/v3.5.4/cmd/argocd-k8s-auth/commands/gcp.go), [Google Kubernetes WIF](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-kubernetes).
