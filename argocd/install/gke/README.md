# GKE 배포 기반과 중앙 EKS Argo CD 연결

이슈 [#37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 GCP 실행 기반이에요. GKE에는 Rollouts를 설치하고, Argo CD·Notifications는 기존 중앙 EKS에서 실행해요.

## 대상과 소유 범위

- 프로젝트 `crystal-sbh2026-gcp-1009`, 클러스터 `tokyo-gke`, `asia-northeast1-a`
- GKE API·kube-system UID는 [target.json](target.json)에 기록해요. 재생성되면 새 UID/API를 확인한 뒤 이 파일과 등록 정보를 함께 갱신해요.
- GCP 담당은 이 디렉터리의 namespace·Rollouts·GKE 배포 RBAC·API 허용 목록·WIF provider·전용 Google 서비스 계정 IAM을 관리해요. `apps/sample-app/overlays/gcp`는 렌더러 생성물이므로 bootstrap을 그 안에 넣지 않아요.
- EKS 담당은 중앙 등록 Secret·EKS Controller/IAM/네트워크와 GCP Application 적용을 관리해요. 등록은 [EKS 연결 요청](../../../docs/gcp-eks-registration-request.md)을 사용해요.
- 공통 카나리·Notifications 템플릿/트리거는 성진님 담당이에요. 기존 성공/Degraded 구독을 GCP 파일에 추가하며, 실패 웹훅 확장 PR #38의 새 트리거 전환은 별도 수신 코드 확인 후 성진님과 진행해요.

## 설치

PowerShell 7과 kubectl, GKE 접근 가능한 별도 kubeconfig가 필요해요. 기본 context나 다른 클러스터 kubeconfig는 바꾸지 않아요.

```powershell
# 저장소 루트에서 실행해요. 출력/캐시는 Git과 동기화하지 않는 로컬 경로를 선택해요.
$gkeConfig = 'C:\private\gke-kubeconfig'
$gkeArtifacts = 'C:\private\crystal-gke-rollouts'
./argocd/install/gke/Install-GkeBootstrap.ps1 `
  -KubeconfigPath $gkeConfig -ArtifactDirectory $gkeArtifacts -ValidateOnly
./argocd/install/gke/Install-GkeBootstrap.ps1 `
  -KubeconfigPath $gkeConfig -ArtifactDirectory $gkeArtifacts
```

스크립트는 API 주소·UID·설치 권한을 확인하고, [공식 v1.10.0 릴리스](https://github.com/argoproj/argo-rollouts/releases/tag/v1.10.0)의 설치 파일을 [고정 SHA256](rollouts-source.json)과 대조해요. 다른 Rollouts 버전이 이미 있으면 덮어쓰지 않고 중단해요. `-ValidateOnly`는 client dry-run이며 실제 admission·Controller Ready 검증은 설치 후 진행해요.

원본 3MB 설치 파일은 Git에 복제하지 않아요. 로컬 Kustomize로 Controller의 requests를 `100m/128Mi`, limits를 `500m/256Mi`로 지정하고 원본 ephemeral-storage limit을 유지해요. 공식 CRD·Controller 역할은 운영자 bootstrap으로 설치하고 앱 배포 계정과 분리해요. server-side apply를 사용하며 namespace·Rollouts·RBAC를 순서대로 적용해요.

## 앱 권한과 인증 인계

Role `sample-app/argocd-deployer`는 namespace 안의 리소스를 get/list/watch할 수 있어 Argo CD의 캐시·상태 조회를 지원해요. 이 조회 범위에는 해당 namespace의 Secret도 포함돼요. 쓰기는 현재 DB 없는 앱의 Service·Rollout·AnalysisTemplate의 create/update/patch/delete에만 허용해요. Secret 쓰기·RBAC 변경·토큰 발급·다른 namespace·노드/클러스터 리소스 권한은 없어요.

기존 Kubernetes SA와 RoleBinding은 유지하고, [별도 RoleBinding](google-deployer-rolebinding.yaml)의 `kind: User`로 전용 Google 서비스 계정 이메일을 같은 Role에 연결해요. 운영 인증은 **EKS OIDC → Google WIF → Google 서비스 계정 impersonation**이고 Kubernetes SA 토큰은 회귀 검증에만 사용해요.

공개 Ingress·DB·Job·Secret을 추가하면 렌더러 출력과 필요한 RBAC를 함께 검토해요. 지금 역할에 쓰기 권한이 있다고 가정하지 않아요. `sample-app-gcp`는 `CreateNamespace=false`로 두며 namespace는 bootstrap이 미리 준비해요.

### WIF 준비

[federation.json](federation.json)은 공개 식별자와 신뢰 조건만 포함해요. global pool은 `crystal-eks`, provider는 `oneaction`이고 EKS issuer의 `argocd-application-controller`와 `argocd-server` subject 두 개만 허용해요. 서비스 계정에는 두 subject 각각의 `roles/iam.workloadIdentityUser`만 연결해요. 프로젝트의 container 역할·Editor·TokenCreator·서비스 계정 키를 추가하지 않아요. [공식 Kubernetes WIF 구성](https://docs.cloud.google.com/iam/docs/workload-identity-federation-with-kubernetes)을 참고해요.

```powershell
./argocd/install/gke/Prepare-GkeFederation.ps1 `
  -KubeconfigPath $gkeConfig -OutputDirectory $gkeArtifacts -PlanOnly
./argocd/install/gke/Prepare-GkeFederation.ps1 `
  -KubeconfigPath $gkeConfig -OutputDirectory $gkeArtifacts
```

스크립트는 실제 프로젝트 번호·API·관리자 kube-system UID와 기존 trust/IAM을 확인한 뒤 필요한 API·pool/provider·전용 계정·IAM·Google RoleBinding을 준비해요. API 허용 목록의 기존 CIDR을 보존하고 EKS 실측 `43.200.199.19/32`만 추가하며 전체 Google 외부 IP 허용은 켜지 않아요. 예상과 다른 기존 trust/IAM은 덮어쓰지 않고 중단해요. PC 송신 주소가 바뀌면 운영자가 실제 주소를 확인해 별도로 접근을 복구해야 해요.

중앙 Argo CD 등록에는 아래 값과 EKS 측의 실제 인증·갱신 검증이 필요해요.

- 등록 이름 `tokyo-gke`, API 주소·CA 검증 `insecure: false`
- `namespaces: sample-app`, `clusterResources: "false"`로 관리 범위를 제한해요. [공식 등록 필드](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters)를 참고해요.
- EKS projected JWT audience는 `https://iam.googleapis.com/projects/19323760731/locations/global/workloadIdentityPools/crystal-eks/providers/oneaction`이에요. external_account ADC audience는 같은 경로의 `//iam.googleapis.com/...` 형식이에요.
- ADC ConfigMap·projected JWT mount·등록 Secret과 실제 WIF 교환·만료 갱신은 EKS 담당이 구성·검증해요. GKE 내부 Workload Identity pool과 이 외부 WIF pool은 별개예요.
- Google access token에는 `cloud-platform`과 `userinfo.email` scope가 필요해요. 이메일 scope가 없으면 GKE가 숫자 uniqueID로 식별해 이메일 RoleBinding에 연결되지 않아요. [GKE 공식 인증 조건](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/api-server-authentication#authenticate_users)과 [Argo CD v3.5.4 구현](https://github.com/argoproj/argo-cd/blob/v3.5.4/cmd/argocd-k8s-auth/commands/gcp.go)을 확인했어요.

스크립트는 운영 등록 토큰·Google 키를 생성/저장하거나 EKS Secret을 적용하지 않아요. TLS를 생략하거나 API를 전체 인터넷에 허용하지 않아요.

## 검증

```powershell
kubectl --kubeconfig $gkeConfig kustomize apps/sample-app/overlays/gcp > $gkeArtifacts/gcp-rendered.yaml
# Python 3 + PyYAML. 기존 Kubernetes SA 회귀 검사예요.
python argocd/install/gke/Verify-GkeBootstrap.py `
  --kubeconfig $gkeConfig --rendered-overlay $gkeArtifacts/gcp-rendered.yaml `
  --output $gkeArtifacts/bootstrap-verification.json

# 운영자는 이 서비스 계정에 한정한 임시 getAccessToken 권한이 있어야 해요.
# 검증 직후 임시 권한을 회수하고 최종 IAM을 다시 확인해요.
python argocd/install/gke/Verify-GkeBootstrap.py `
  --kubeconfig $gkeConfig --rendered-overlay $gkeArtifacts/gcp-rendered.yaml `
  --google-service-account argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com `
  --output $gkeArtifacts/google-rbac-verification.json
```

검증은 Controller Ready·고정 이미지·CRD 5개의 Established와 실제 인증을 확인해요. namespace 조회·대상 Kubernetes SA UID 조회와 현재 앱 리소스의 server dry-run create는 성공해야 하고, kube-system/노드 조회·Secret 쓰기·권한 상승·토큰 발급은 HTTP 403이어야 해요. Google 계정 검사는 쓰기 12개 허용과 namespace/ClusterRole/Secret 확장 3개 거부를 SelfSubjectAccessReview로 추가 확인해요. 이 API의 HTTP 201은 검사 요청 성공이며 권한은 응답의 `allowed` 값으로 판정해요. 15분 토큰은 메모리에만 유지하고 token·API 응답 본문은 보고서에 넣지 않아요. app 리소스는 이 검증으로 실제 생성되지 않아요. 운영자 impersonation 검사는 EKS의 WIF 교환·갱신 검사와 구분해요.

EKS 담당의 등록과 Application 적용 이후에는 아래 항목을 별도로 확인해요.

- 실제 GKE UID·Application destination·GitOps revision·Pod 이미지/Ready
- GKE Service 내부 `/healthz`·`/api/info` HTTP 200, `environment=gcp`·`region=asia-northeast1`·버전 일치
- GKE `sample-app`의 AnalysisTemplate 존재와, 후속 업데이트 시 AnalysisRun/카나리 결과. 최초 배포만으로 카나리 분석 성공을 판단하지 않아요.
- 중앙 Notifications의 app/env/images/revision와 Review API의 GCP 배포 기록. GCP 검토 기록과 매칭되지 않은 이벤트 수신은 gcp baseline 완료가 아니에요.

현재 GCP overlay에는 Ingress가 없어요. 공개 LB·NEG/health check·외부 응답은 연재님 렌더러 보완과 연결하는 후속 작업이에요. GKE Prometheus를 설치하거나 공통 메트릭 분석 URL을 임의로 바꾸지 않아요.

### 실제 확인과 활성화 대기

2026-10-09 GKE에서 Controller Ready·CRD 5개·실제 SA 인증/RBAC 10개 검사를 통과했어요. 최신 main의 GCP overlay는 Service·AnalysisTemplate·Rollout server dry-run을 통과했지만, dry-run은 카나리 실행 성공을 확인하지 않아요.

[PR #39](https://github.com/Crystal-SBHackathon2026/gitops/pull/39)가 추가한 공통 `error-rate`만 임시 AnalysisRun으로 실행했어요. GKE에 Prometheus가 없어 7회 연속 DNS 오류 후 `Error`로 종료됐어요. `count=6`, `consecutiveErrorLimit=6`이면 오류를 무시한다는 조건은 성립하지 않았어요. 시험 AnalysisRun은 삭제했어요.

이후 성진님이 [PR #42](https://github.com/Crystal-SBHackathon2026/gitops/pull/42)를 머지해 공통 `error-rate`와 사용하지 않는 canary-hash 인자를 제거했어요. 현재 AWS·로컬·GCP 모두 `api-ok`만 사용하므로 GCP의 Prometheus 차단 조건은 해소됐어요. 환경별 에러율 분석 복원은 렌더러 보완 또는 측정 백엔드의 팀 합의가 필요하지만 첫 GCP 연결의 선행 조건과 분리해요. GKE Prometheus는 추가 설치하지 않았어요.

2026-10-10 EKS 실측 egress `43.200.199.19/32`를 추가하고 위 WIF/IAM/Google RoleBinding을 준비했어요. 실제 Google 계정 RBAC 26개와 기존 Kubernetes SA 회귀 11개 검사를 통과했어요. [WIF 검증 기록](../../../docs/gcp-wif-verification-2026-10-10.md)에 실패 원인·조치·최종 설정을 기록해요. EKS 실제 WIF 교환·만료 갱신·클러스터 등록과 앱 실행 검증은 남아 있어요.

성진님의 [PR #45](https://github.com/Crystal-SBHackathon2026/gitops/pull/45)는 2026-10-10 확인 시 OPEN이에요. 머지되면 overlay와 `analysis/default` 두 소스를 GCP Application에 반영하고 기존 app/env와 구독·`CreateNamespace=false`를 보존해요. 이 준비만으로 Application을 적용하지 않아요. [기존 검증 기록](../../../docs/gcp-gke-verification-2026-10-09.md)과 [연재님 능력표 인계](../../../docs/gcp-gke-capability-handoff.md)도 함께 참고해요.

## 회수와 운영 종료

운영 종료 목표는 2026-10-12 23:59 KST이고 사용자가 직접 삭제해요. 10월 13일 00:00의 예약은 읽기 전용 종료 점검이에요.

- GCP Application 동기화를 먼저 EKS 담당과 중단하고, 앱/Ingress/LB·PVC의 보존 여부를 확인해요.
- 등록 인증을 폐기한 뒤 Google RoleBinding·서비스 계정 IAM·전용 WIF provider/pool·계정을 회수해요. 중앙 클러스터 Secret 삭제는 EKS 담당이 진행해요. 다른 사용자가 재사용하는지 먼저 확인해요.
- Rollouts CRD를 먼저 삭제하면 관리 중인 앱이 손상될 수 있어요. 공유/잔여 Rollout·Analysis 리소스를 확인한 뒤 GKE 전체 종료 또는 Controller/CRD 회수 순서를 정해요.
- 클러스터·디스크 삭제와 남은 LB/IP 정리는 사용자 수동 작업이에요. 이 설치/검증 스크립트는 삭제·증설·유료 DB 생성을 실행하지 않아요.
