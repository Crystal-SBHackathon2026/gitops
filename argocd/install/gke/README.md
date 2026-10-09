# GKE 배포 기반과 중앙 EKS Argo CD 연결

이슈 [#37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 GCP 실행 기반이에요. GKE에는 Rollouts를 설치하고, Argo CD·Notifications는 기존 중앙 EKS에서 실행해요.

## 대상과 소유 범위

- 프로젝트 `crystal-sbh2026-gcp-1009`, 클러스터 `tokyo-gke`, `asia-northeast1-a`
- GKE API·kube-system UID는 [target.json](target.json)에 기록해요. 재생성되면 새 UID/API를 확인한 뒤 이 파일과 등록 정보를 함께 갱신해요.
- GCP 담당은 이 디렉터리의 namespace·Rollouts·GKE 배포 RBAC·API 허용 목록을 관리해요. `apps/sample-app/overlays/gcp`는 렌더러 생성물이므로 bootstrap을 그 안에 넣지 않아요.
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

`sample-app/argocd-deployer`는 namespace 안의 리소스를 get/list/watch할 수 있어 Argo CD의 캐시·상태 조회를 지원해요. 이 조회 범위에는 해당 namespace의 Secret도 포함돼요. 쓰기는 현재 DB 없는 앱의 Service·Rollout·AnalysisTemplate에만 허용해요. Secret 쓰기·RBAC 변경·토큰 발급·다른 namespace·노드/클러스터 리소스 권한은 없어요.

공개 Ingress·DB·Job·Secret을 추가하면 렌더러 출력과 필요한 RBAC를 함께 검토해요. 지금 역할에 쓰기 권한이 있다고 가정하지 않아요. `sample-app-gcp`는 `CreateNamespace=false`로 두며 namespace는 bootstrap이 미리 준비해요.

중앙 Argo CD 등록에는 아래 값과 **별도 합의한 인증 공급·갱신 방식**이 필요해요.

- 등록 이름 `tokyo-gke`, API 주소·CA 검증 `insecure: false`
- `namespaces: sample-app`, `clusterResources: "false"`로 관리 범위를 제한해요. [공식 등록 필드](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/#clusters)를 참고해요.
- EKS Controller/server의 실제 egress IPv4를 확인한 뒤 GKE API 허용 목록에 추가해요. 기존 작업 PC의 허용 항목은 유지해요.
- Kubernetes SA TokenRequest 방식이면 실제 만료 시각·갱신 담당과 전달 경로를 정해요. 개인 OAuth 토큰을 복사하거나 무기한 SA 토큰 Secret을 기본으로 생성하지 않아요.
- GCP IAM federation 방식이면 EKS 워크로드 주체·GCP 권한·갱신을 양쪽 담당이 맞춰요. GKE Workload Identity 활성만으로 EKS 인증이 연결되지는 않아요. 인증 주체가 바뀌면 RoleBinding subject도 맞춰요.

스크립트는 운영 등록 토큰·Google 키를 생성/저장하거나 EKS Secret을 적용하지 않아요. TLS를 생략하거나 API를 전체 인터넷에 허용하지 않아요.

## 검증

```powershell
kubectl --kubeconfig $gkeConfig kustomize apps/sample-app/overlays/gcp > $gkeArtifacts/gcp-rendered.yaml
# Python 3 + PyYAML. 15분 검증용 TokenRequest는 메모리에만 유지해요.
python argocd/install/gke/Verify-GkeBootstrap.py `
  --kubeconfig $gkeConfig --rendered-overlay $gkeArtifacts/gcp-rendered.yaml `
  --output $gkeArtifacts/bootstrap-verification.json
```

검증은 Controller Ready·고정 이미지·CRD 5개의 Established와 실제 SA 인증을 확인해요. namespace 조회와 현재 앱 리소스의 server dry-run create는 성공해야 하고, kube-system/노드 조회·Secret 쓰기·권한 상승·토큰 발급은 HTTP 403이어야 해요. token·API 응답 본문은 보고서에 넣지 않아요. app 리소스는 이 검증으로 실제 생성되지 않아요.

EKS 담당의 등록과 Application 적용 이후에는 아래 항목을 별도로 확인해요.

- 실제 GKE UID·Application destination·GitOps revision·Pod 이미지/Ready
- GKE Service 내부 `/healthz`·`/api/info` HTTP 200, `environment=gcp`·`region=asia-northeast1`·버전 일치
- GKE `sample-app`의 AnalysisTemplate 존재와, 후속 업데이트 시 AnalysisRun/카나리 결과. 최초 배포만으로 카나리 분석 성공을 판단하지 않아요.
- 중앙 Notifications의 app/env/images/revision와 Review API의 GCP 배포 기록. GCP 검토 기록과 매칭되지 않은 이벤트 수신은 gcp baseline 완료가 아니에요.

현재 GCP overlay에는 Ingress가 없어요. 공개 LB·NEG/health check·외부 응답은 연재님 렌더러 보완과 연결하는 후속 작업이에요. GKE Prometheus를 설치하거나 공통 메트릭 분석 URL을 임의로 바꾸지 않아요.

## 회수와 운영 종료

운영 종료 목표는 2026-10-12 23:59 KST이고 사용자가 직접 삭제해요. 10월 13일 00:00의 예약은 읽기 전용 종료 점검이에요.

- GCP Application 동기화를 먼저 EKS 담당과 중단하고, 앱/Ingress/LB·PVC의 보존 여부를 확인해요.
- 등록 인증을 폐기한 뒤 GCP RoleBinding·SA를 회수해요. 중앙 클러스터 Secret 삭제는 EKS 담당이 진행해요.
- Rollouts CRD를 먼저 삭제하면 관리 중인 앱이 손상될 수 있어요. 공유/잔여 Rollout·Analysis 리소스를 확인한 뒤 GKE 전체 종료 또는 Controller/CRD 회수 순서를 정해요.
- 클러스터·디스크 삭제와 남은 LB/IP 정리는 사용자 수동 작업이에요. 이 설치/검증 스크립트는 삭제·증설·유료 DB 생성을 실행하지 않아요.
