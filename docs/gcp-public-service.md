# 도쿄 sample-app HTTP 공개 경로

[이슈 #66](https://github.com/Crystal-SBHackathon2026/gitops/issues/66)의 GCP 외부 접속 구성이에요. 기존 `sample-app-gcp` Application이 main을 동기화하고, GKE가 active Service의 외부 LoadBalancer를 관리해요. 실제 주소를 혜연님의 `localhost:5050` 서버 프록시에 연결해요.

## 구성과 담당

| 항목 | 값 또는 담당 |
| --- | --- |
| 대상 | `crystal-sbh2026-gcp-1009` / `asia-northeast1-a` / `tokyo-gke` |
| 대상 API·UID | [GKE target.json](../argocd/install/gke/target.json) |
| active | `sample-app/sample-app`, `LoadBalancer`, TCP 80 → HTTP 앱 8080 |
| preview | `sample-app/sample-app-preview`, 내부 `ClusterIP` |
| 공개 패치 | [service-public.yaml](../apps/sample-app/overlays/gcp/service-public.yaml) |
| 수동 승격 | 기존 `autoPromotionEnabled: false`; 성진님과 실행·전환 결과 확인 |
| GCP 담당 | 공개 Service·GKE LB/방화벽 조회·외부 응답·운영 종료 회수 확인 |
| 화면 담당 | 혜연님의 5050 서버 프록시 주소 등록·버전 표시·자동 새로고침 확인 |
| 중앙 Application·알림 | 성진님이 관리하는 기존 구성을 재사용 |
| EKS 실행 기반·등록 인증 | EKS 담당의 기존 구성을 재사용 |

패치는 기존 active Service에 `spec.type: LoadBalancer`만 추가해요. 공통 base와 preview Service, Service 이름·포트·selector, Rollout 전략은 기존 구성을 사용해요. `rollouts-pod-template-hash`는 Rollouts가 관리하므로 패치에 고정하지 않아요. Service UID·ClusterIP를 유지한 갱신인지 실제 API에서 확인해요.

현재 GKE `1.35.8-gke.1380001`에서 별도 LB class/annotation을 지정하지 않는 이 구성은 target pool 기반 external passthrough Network LoadBalancer를 사용해요. GKE 버전에 따라 기본 구현이 달라지므로 생성 뒤 forwarding rule의 target/backend와 실제 health를 대조해요. [GKE 공식 Service 파라미터](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/service-load-balancer-parameters)와 [LB 동작](https://docs.cloud.google.com/kubernetes-engine/docs/concepts/service-load-balancer)을 참고해요. GKE가 관리하는 finalizer·LB health check·방화벽을 직접 수정하지 않아요.

이번 경로는 HTTP예요. 5050 서버가 `/api/info`를 프록시하므로 브라우저의 직접 요청을 위한 CORS 변경은 필요하지 않아요. TLS 종료·도메인·인증서는 별도 요구가 생기면 검토해요.

## 이미지 갱신과 렌더러 적용 조건

현재 sample-app 명세는 AWS 한 환경을 검토하며, CI가 `apps/sample-app/base/kustomization.yaml`의 이미지 태그를 바꿔요. GCP overlay는 현재 수동 블루그린 구성이므로 이 공개 패치가 다음 base 이미지 갱신에도 유지돼요. 정적 이미지 갱신 시뮬레이션과 실제 후속 CI 배포 결과는 구분해요.

연재님의 [review-service PR #67](https://github.com/Crystal-SBHackathon2026/review-service/pull/67)과 같은 파일 이름·최소 patch 구조를 재사용해요. 해당 PR과 기반 다중 환경 [PR #64](https://github.com/Crystal-SBHackathon2026/review-service/pull/64)는 현재 데모에 반영하지 않아요. 향후 GCP 명세를 실제로 렌더링할 때는 아래 공개 계약과 수동 승격을 포함한 출력·삭제 보호를 먼저 검증해요.

```yaml
network:
  service:
    type: LoadBalancer
    public: true
rollout:
  strategy: bluegreen
  auto_promotion: false
```

`commit_overlay`가 GCP overlay를 재생성하면 수동 파일도 삭제될 수 있어요. 이번 구현으로 아직 main에 없는 공개 Service 삭제 보호나 전체 환경 gate가 활성화된 것으로 취급하지 않아요.

## PR 머지 전 검증

overlay와 Application의 두 번째 source를 함께 확인해요. overlay는 Service 2개·Rollout 1개, `analysis/default`는 AnalysisTemplate 1개예요. 템플릿 존재와 분석 실행 성공은 구분해요.

```powershell
kubectl kustomize apps/sample-app/overlays/gcp
kubectl kustomize apps/sample-app/analysis/default
kubectl kustomize apps/sample-app/overlays/aws
kubectl kustomize apps/sample-app/overlays/local
git diff --check
```

기존 운영자 kubeconfig로 API와 UID를 확인해요. `--raw`로 인증값을 출력하지 않아요.

```powershell
$GkeConfig = (Resolve-Path '<GKE kubeconfig 절대 경로>').Path
$target = Get-Content argocd/install/gke/target.json -Raw | ConvertFrom-Json
$contextView = kubectl --kubeconfig $GkeConfig config view --minify -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $contextView.clusters[0].cluster.server.TrimEnd('/') -ne $target.server) {
  throw 'Unexpected GKE API'
}
$actualUid = kubectl --kubeconfig $GkeConfig --request-timeout=15s get namespace kube-system -o 'jsonpath={.metadata.uid}'
if ($LASTEXITCODE -ne 0 -or $actualUid -ne $target.kubeSystemUid) { throw 'Unexpected GKE UID' }
kubectl --kubeconfig $GkeConfig --request-timeout=15s apply --dry-run=server -k apps/sample-app/overlays/gcp
if ($LASTEXITCODE -ne 0) { throw 'GCP server dry-run failed' }
```

운영자 dry-run과 실제 중앙 Google 배포 계정의 권한 검사를 구분해요. 기존 EKS Pod의 공식 WIF 인증으로 실제 계정을 확인한 뒤 Service get/patch/update 허용, 다른 namespace·Secret 쓰기·RBAC 변경·노드 조회 거부와 기존 active Service의 타입 변경 `dryRun=All`을 확인해요. 인증 출력은 메모리에서만 처리해요. 이 검사는 실제 Service·EKS 리소스·유료 LB를 생성하지 않아요.

중앙 Application은 `targetRevision: main`, 자동 동기화·selfHeal 구성이에요. 작업 브랜치의 패치를 운영 Service에 수동 적용하면 main의 ClusterIP 선언과 충돌해요. 이번 변경은 PR 머지 후 기존 Application 동기화로 적용하고, 실제 LB 생성·외부 응답 검증 결과를 이어서 기록해요.

## PR 머지 후 실제 공개 경로 확인

1. 성진님과 중앙 Application의 목적지 `tokyo-gke/sample-app`, 두 source의 실제 revision, Service 동기화 결과를 대조해요.
2. 기존 active Service UID·ClusterIP와 preview의 내부 타입을 확인하고 외부 IP를 기다려요. `Synced` 표시만으로 완료하지 않아요.
3. 외부 응답과 GKE Pod 이미지/버전, GKE가 만든 LB target/health·방화벽을 대조해요.
4. 실제 주소를 혜연님께 전달하고 5050 서버 프록시의 도쿄 카드·자동 새로고침을 확인해요.

```powershell
kubectl --kubeconfig $GkeConfig --request-timeout=15s get service sample-app sample-app-preview -n sample-app -o wide
kubectl --kubeconfig $GkeConfig --request-timeout=15s get pods -n sample-app -l app=sample-app -o wide
$activeService = kubectl --kubeconfig $GkeConfig --request-timeout=15s get service sample-app -n sample-app -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Active Service readback failed' }
$TokyoHost = @($activeService.status.loadBalancer.ingress | Where-Object { $_.ip })[0].ip
if (-not $TokyoHost) { throw 'LoadBalancer address is not ready' }
$TokyoUrl = 'http://' + $TokyoHost
$healthResponse = Invoke-WebRequest -Uri ($TokyoUrl + '/healthz') -TimeoutSec 10 -UseBasicParsing
$infoResponse = Invoke-WebRequest -Uri ($TokyoUrl + '/api/info') -TimeoutSec 10 -UseBasicParsing
if ($healthResponse.StatusCode -ne 200 -or $infoResponse.StatusCode -ne 200) { throw 'Unexpected HTTP status' }
$info = $infoResponse.Content | ConvertFrom-Json
if ($info.environment -ne 'gcp' -or $info.region -ne 'asia-northeast1') { throw 'Unexpected service environment' }
[pscustomobject]@{url=$TokyoUrl; environment=$info.environment; region=$info.region; version=$info.version}
gcloud compute forwarding-rules list --project $target.project --filter "IPAddress=$TokyoHost" `
  --format='table(name,region,IPAddress,IPProtocol,portRange,ports,target,backendService)'
if ($LASTEXITCODE -ne 0) { throw 'Forwarding rule readback failed' }
```

target pool 방식이면 위 조회의 실제 target pool 이름으로 `gcloud compute target-pools get-health <이름> --region asia-northeast1 --project $target.project`를 확인해요. backend service 방식이면 실제 이름에 맞는 `backend-services get-health`를 사용해요. 방화벽의 Service VIP·허용 포트와 preview에 별도 forwarding rule이 없는지도 확인해요. 조회 예시의 이름을 추측해 운영 자원을 수정하지 않아요.

## 같은 주소의 수동 전환과 후속 CI

- 다음 정상 이미지가 들어오면 active·preview selector와 각 내부 응답 버전을 기록해요. 승격 대기 중 공개 URL은 기존 active 버전을 계속 반환해야 해요.
- 성진님이 기존 Argo CD UI의 Promote를 실행해요. 같은 Service UID·IP·공개 URL에서 새 버전으로 바뀌고 Pod Ready·Rollout/Application Healthy가 되는지 함께 확인해요.
- 실제 후속 CI의 이미지 태그 변경에서도 공개 타입·주소와 preview의 내부 타입이 유지되는지 확인해요. 이미지 전달 SHA와 GitOps revision은 각각 기록해요.
- 실제 승격·화면·후속 CI가 확인될 때까지 이슈의 해당 완료 조건을 남겨둬요. GCP 알림 수신·검토 기록·baseline과 앱 트래픽 중 인증 자동 갱신은 기존 [GKE 연결 작업](../argocd/install/gke/README.md)의 후속 검증이에요.

## 운영 기간·비용·수동 회수

LB 1개를 생성 시점부터 2026-10-12 23:59 KST까지 운영하는 계획이에요. 약 48시간 기준 forwarding rule 비용은 약 USD 1.20이며, 도쿄 데이터 처리 비용은 inbound/outbound 각각 USD 0.012/GiB, 인터넷 송신·세금은 별도예요. [공식 LB 가격표](https://cloud.google.com/load-balancing/pricing)를 기준으로 해요. 무료 크레딧 적용 여부는 미확인이에요. 운영 기간 종료만으로 과금 자원이 삭제되지는 않으며 사용자가 직접 삭제해요.

이번 구성은 예약 IP를 따로 만들지 않아요. 같은 Service를 유지하는 동안의 주소 보존을 검증하며, Service를 삭제·재생성하거나 클러스터를 재생성한 뒤에도 같은 주소라고 가정하지 않아요.

1. 삭제 전에 현재 Service·외부 IP·forwarding rule·target/health check·연결된 방화벽과 예약 IP 유무를 기록해요.
2. LB만 회수할 때는 별도 GitOps 변경으로 `service-public.yaml` patch 참조와 파일을 제거하고 GCP active Service가 ClusterIP로 동기화되게 해요. 먼저 Git의 선언을 바꿔 main의 selfHeal이 LB를 다시 만들지 않게 해요.
3. GKE Controller의 LB 정리를 기다린 뒤 해당 IP의 forwarding rule·연결된 target/health check·Service 전용 방화벽이 사라졌는지 확인해요. preview와 내부 서비스도 다시 확인해요. 공유 health check·클러스터 공통 방화벽을 이름만 보고 삭제하지 않아요.
4. 클러스터 전체를 종료할 때는 성진님과 중앙 Application의 자동 재생성을 중지한 뒤 사용자가 클러스터를 직접 삭제해요. 남은 LB·디스크·예약 IP를 GCP에서 별도로 조회해요.

실제 삭제 명령과 자동 삭제 예약은 이 변경에 포함하지 않아요. 이미 예약한 2026-10-13 00:00 KST 점검은 읽기 전용이에요.

## 검증 기록 — 2026-10-11

| 구분 | 결과 |
| --- | --- |
| 00:34 KST 실제 대상·내부 배포 | target.json의 kube-system UID 일치, GKE RUNNING·1.35.8, 중앙 Application Synced/Healthy·두 source revision `9b1a31d` |
| 00:34 KST 앱 | Rollout Healthy·수동 승격 설정 유지, 최신 이미지 `0e402802ea345ed5503a5f298f40fb49f887ae54`의 Pod 2개 Ready, active/preview selector `6d7f7645d7` |
| 00:34 KST Service·클라우드 | active UID `fb466af7-ebeb-483f-8479-d2081a12f515`·ClusterIP `10.62.3.1`, preview UID `50e182af-354b-472d-abf0-07fc94212e90`·ClusterIP `10.62.12.245`; 두 Service는 아직 ClusterIP, 프로젝트 forwarding rule 0개 |
| 00:39 KST 정적 회귀·CI 시뮬레이션 | AWS/local·두 Analysis 출력은 main과 동일, GCP는 active Service 타입만 변경, GCP 두 source 리소스 4개·preview 내부·수동 승격 유지와 다음 base 이미지 태그 변경 시 공개 설정 보존을 통과했어요. 로컬 문서 링크 11개와 diff 검사를 통과했고 PowerShell 예제 3개는 구문 검사만 했어요. |
| 00:37 KST 실제 배포 계정·Service dry-run | 기존 EKS Pod의 공식 WIF로 Google 배포 계정을 확인하고 13개 검사를 통과했어요. Service get/patch/update 허용·범위 밖 거부, 기존 active의 LoadBalancer strategic merge dry-run HTTP 200·UID/ClusterIP/selector 보존·80→8080, 두 내부 Service의 health/info HTTP 200·gcp/asia-northeast1·버전 `0e402802ea345ed5503a5f298f40fb49f887ae54`를 확인했어요. 실제 Service·EKS 리소스·LB는 변경하지 않았어요. |
| PR 머지 후 확인 | 실제 LB/외부 URL·외부 HTTP·5050 화면·승격 전후 전환·후속 CI는 아직 미검증이에요. |

위 시각의 상태 조회만으로 누가 Promote를 실행했는지 확정하지 않아요. 팀원의 실행 결과와 실제 서비스 전환 관찰은 별도로 대조해요.
