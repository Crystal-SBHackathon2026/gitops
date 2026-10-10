# 도쿄 sample-app HTTP 공개 경로

[이슈 #66](https://github.com/Crystal-SBHackathon2026/gitops/issues/66)의 GCP 외부 접속 구성이에요. 기존 `sample-app-gcp` Application이 main을 동기화하고, GKE가 active Service의 외부 LoadBalancer를 관리해요. 실제 주소를 혜연님의 `localhost:5050` 서버 프록시에 연결해요.

2026-10-11 01:10 KST에 [PR #68](https://github.com/Crystal-SBHackathon2026/gitops/pull/68)의 실제 공개 경로 `http://34.85.123.113`과 외부 `/healthz`·`/api/info` HTTP 200을 확인했어요. 응답은 `gcp/asia-northeast1`, 버전은 `0e402802ea345ed5503a5f298f40fb49f887ae54`예요. 5050 화면과 새 preview의 승격 전후 전환은 공동 검증으로 남아 있어요.

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

연재님의 [review-service PR #67](https://github.com/Crystal-SBHackathon2026/review-service/pull/67)의 기존 렌더러·`commit_overlay` 삭제 보호를 재사용해요. 2026-10-11 02:08 KST에 PR head `543b624`와 gitops main `c180dcd`로 공개 Service 테스트 6개·현재 base 호환성 검사 18개를 통과했어요. 기준 SHA·검사 범위·예제 차이는 [공개 명세 검증 기록](gcp-public-spec-verification-2026-10-11.md)에 있어요. 실제 팀 PR A의 최종 파일을 검증한 결과는 아니에요.

아래는 GCP 명세의 일부예요. `target.env: gcp`, `target.region: asia-northeast1`, `target.namespace: sample-app`, `metadata.name: sample-app`, `runtime.port: 8080`과 함께 검증해요. 실제 선택 요청의 GCP 항목은 등록 목록의 `env/region/cluster`와 맞아야 해요. active `sample-app`과 preview `sample-app-preview`, 포트 80→8080·기존 base를 유지해요.

```yaml
network:
  service:
    type: LoadBalancer
    public: true
rollout:
  strategy: bluegreen
  auto_promotion: false
```

수동 승격 입력에는 `auto_promotion_seconds: 30`을 함께 넣지 않아요. `network.service`는 GCP active만 공개하며, 같은 명세의 Ingress 지정·AWS/local 공개 Service·NodePort는 PR #67 모델에서 거절해요. patch에는 selector·ClusterIP·Rollouts hash를 넣지 않아요.

기존 [sample-app PR #38 공개 예제](https://github.com/Crystal-SBHackathon2026/sample-app/blob/353c6afd8fba93ae6a6ac32208d49f133e70fe76/examples/multi-target/deploy/gcp.yaml)는 공개 설정이 없고 replicas 3·자동 승격 30초예요. 현재 도쿄 replicas 2·수동 승격과 달라요. 이 예제로 기존 공개 overlay를 재생성하면 PR #67 guard/commit이 `OVERLAY_RESOURCE_REMOVED: service-public.yaml`로 차단해요. [gitops PR #56 안내](https://github.com/Crystal-SBHackathon2026/gitops/blob/2bc81497eddaf27fac5c4a42a5f90e90a47daf26/examples/multi-target/README.md)의 자동 승격 30초 설명도 현재 도쿄 계약에 맞춰 대조해야 해요.

연재님의 [로컬 PR A 준비 기록](https://github.com/Crystal-SBHackathon2026/review-service/blob/543b6247ae3d9aedee550fb1ac0a640b63b168b7/docs/slack-demo-followups.md)은 공개 Service·수동 승격을 포함한 별도 입력을 설명해요. 공개 예제와 같은 파일로 취급하지 않아요. 연재님·성진님과 실제 `deploy/gcp.yaml` 최종 내용 및 전체 렌더링을 활성화 전에 대조해요.

### 명세 기반 배포를 활성화하는 순서

2026-10-11 02:22 KST 확인 시 review-service PR #62→#63→#64→#67, sample-app PR #38, gitops PR #56은 OPEN/Draft예요. 준비된 PR과 현재 운영 실행 버전을 구분해요. [원 구현의 활성화 안내](https://github.com/Crystal-SBHackathon2026/review-service/blob/543b6247ae3d9aedee550fb1ac0a640b63b168b7/docs/multi-target.md)를 따라 담당자가 다음 순서를 맞춰요.

1. 실제 PR A 입력을 받아 공개 계약·삭제 보호·Service 두 개·수동 승격·현재 base 출력과의 차이를 오프라인으로 검증해요. 현재 AWS 루트 `deploy.yaml`에 GCP 전용 필드를 추가하지 않아요. 기존 스키마에 새 공개 필드를 먼저 보내면 `schema_error`가 나요.
2. 연재님·혜연님이 선행 review-service PR의 main 반영, 의존 브랜치/CI, 새 스키마·renderer·guard 포함을 확인해요. 문서상의 PR head만으로 운영 적용을 판단하지 않아요.
3. API와 모든 worker를 같은 새 코드로 배포하되 `MULTI_TARGET_ENABLED=false`를 유지해요. API·worker 실제 이미지 SHA와 migration 0013 적용·기존 인덱스 유지 상태는 해당 담당자가 확인해요. NET-001 지식의 S3·Qdrant 동기화도 연재님·혜연님 확인 항목이에요.
4. 성진님과 sample-app PR #38의 CI·repository variable 전환 시점, API/worker의 동일한 `DEPLOYMENT_TARGETS_JSON`을 맞춰요. GCP 항목은 `gcp/asia-northeast1/tokyo-gke`예요. PR #56 등록 예제 자체는 실제 클러스터 접근 증거가 아니에요. local의 자체 Argo CD 경로도 중앙 EKS 등록으로 간주하지 않아요.
5. 진행 중 요청과 GitOps 동시 쓰기를 확인하고 API·모든 worker·CI의 활성화 시점을 합의해요. 이전 worker와 새 worker를 섞어 활성화하지 않아요. 새 단일 명세 CI는 선택 overlay를 갱신하고, 다중 환경 요청은 CI 빌드 성공 뒤 coordinator가 선택 환경을 한 GitOps 커밋으로 반영해요. 같은 대상의 수동 이미지 갱신을 동시에 진행하지 않아요.
6. 합의한 활성화 뒤 별도 앱 PR로 실제 검토→CI→GitOps→GKE를 확인해요. GCP 재생성 출력의 server dry-run과 실제 UID·ClusterIP·외부 IP·selector, Pod·버전·알림을 확인하고 성진님·혜연님과 승격/5050 검증을 이어가요.

분석 입력에서는 렌더러가 `terminationGracePeriodSeconds: 30`을 Pod template에 추가하는 차이도 있었어요. 전략·Service 비교 통과만으로 전체 Rollout이 같다고 판단하지 않아요. 실제 재생성 후 preview·Pod 교체 여부는 위 공동 검증에서 확인해요.

`MULTI_TARGET_ENABLED=false`만으로 DB 인덱스나 overlay 이미지 pin이 원래대로 복구되지는 않아요. 활성화/롤백은 API·worker 담당과 진행 중 요청·DB 호환성·이미지 쓰기 경로를 함께 확인해요. 이 문서 변경은 플래그·CI·실제 클러스터를 변경하지 않아요.

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

중앙 Application은 `targetRevision: main`, 자동 동기화·selfHeal 구성이에요. PR #68의 공개 패치는 main 반영 뒤 기존 Application이 동기화했어요. 후속 변경도 Git의 선언과 실제 source revision을 대조해요. 작업 브랜치를 운영 Service에 수동 적용하는 방식은 사용하지 않아요.

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

성진님은 [00:43 KST 작업 스레드 답장](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791647036188569)에서 00:15에 수동 승격했다고 알려주셨어요. 직접 조회한 active·preview selector도 모두 `6d7f7645d7`이고 버전은 `0e402802ea345ed5503a5f298f40fb49f887ae54`예요. 현재는 승격을 기다리는 새 preview가 없으므로 LB 연결만으로 승격 전후 전환까지 검증할 수 없어요.

- LB 연결 뒤 현재 active 버전의 외부 `/healthz` HTTP 200·`/api/info`의 `gcp/asia-northeast1`·이미지 SHA 일치를 01:10 KST에 확인했어요. 공개 주소를 전달했고 5050 프록시·화면 연결 결과를 확인해요.
- 리허설 PR A가 병합되고 실제 CI 이미지 갱신이 GCP에 반영되면 성진님과 Rollout Paused·서로 다른 active/preview selector·각 내부 응답 버전을 기록해요. 승격 대기 중 공개 URL은 기존 active 버전을 계속 반환해야 해요. 별도 테스트 이미지나 FAIL_RATE PR을 추가하지 않아요.
- 성진님이 기존 Argo CD UI의 Promote를 실행해요. 같은 Service UID·IP·공개 URL에서 새 버전으로 바뀌고 Pod Ready·Rollout/Application Healthy가 되는지 함께 확인해요.
- 리허설의 실제 후속 CI 이미지 태그 변경에서도 공개 타입·주소와 preview의 내부 타입이 유지되는지 함께 확인해요. 이미지 전달 SHA와 GitOps revision은 각각 기록해요.
- 실제 승격·화면·후속 CI가 확인될 때까지 이슈의 해당 완료 조건을 남겨둬요. GCP 알림 수신·검토 기록·baseline과 앱 트래픽 중 인증 자동 갱신은 기존 [GKE 연결 작업](../argocd/install/gke/README.md)의 후속 검증이에요.

현재 AWS 단일 명세 데모에서는 base 이미지 변경이 GCP 수동 블루그린에도 전달돼요. 연재님의 로컬 PR A는 새 다중 환경 기능을 전제로 한 통합 입력이므로, 현재 모드의 이미지 전환 검증과 구분해요. 어느 PR A와 CI 모드로 리허설할지 성진님·연재님과 먼저 맞춰요.

## 공개 IP의 모니터링·화면 의존성

2026-10-11 02:35 KST에 머지된 성진님의 [PR #71](https://github.com/Crystal-SBHackathon2026/gitops/pull/71)은 서울 Prometheus에서 도쿄 공개 주소의 `/metrics`를 수집해요. [monitoring/external/tokyo.yaml](../monitoring/external/tokyo.yaml)의 EKS `monitoring/sample-app-tokyo` Endpoints가 `34.85.123.113:80`을 참조하고 ServiceMonitor는 `/metrics`를 30초 간격으로 수집해요. GKE에 Prometheus를 추가하는 구성은 아니에요.

성진님 PR에는 타깃 up·`env` 라벨 `aws/gcp`·Prometheus 재시작 0회를 확인한 결과가 있어요. 이 채팅의 직접 EKS 실측 결과와 구분해요. 기존 GCP 외부 HTTP 응답 검증만으로 중앙 Prometheus 수집·Grafana 화면까지 완료했다고 판단하지 않아요.

- 수동 승격·후속 CI에서는 같은 active Service·공개 IP를 유지하는지 확인해요. 같은 IP를 유지하면 Endpoints의 목적지는 그대로 사용할 수 있어요.
- LB/Service를 재생성해 IP가 바뀌면 GCP 담당이 새 실제 IP·환경/버전·외부 응답을 확인하고 성진님·EKS 담당에게 기존 IP→새 IP와 위 Endpoints 변경 요청을 전달해요. 담당자의 GitOps 반영 뒤 실제 타깃 up·`env=gcp` 지표를 확인하고, 혜연님의 5050 프록시 주소도 함께 갱신·검증해요.
- LB 회수 전에 성진님·EKS 담당과 해당 수집 연결의 중지/정리, 혜연님과 도쿄 카드 처리를 맞춰요. ServiceMonitor·Endpoints·중앙 Application의 정리는 해당 담당의 별도 GitOps 변경으로 진행해요. 이 채팅에서 EKS 리소스나 Prometheus CR을 수정하지 않아요.

## 운영 기간·비용·수동 회수

LB 1개를 생성 시점부터 2026-10-12 23:59 KST까지 운영하는 계획이에요. 약 48시간 기준 forwarding rule 비용은 약 USD 1.20이며, 도쿄 데이터 처리 비용은 inbound/outbound 각각 USD 0.012/GiB, 인터넷 송신·세금은 별도예요. [공식 LB 가격표](https://cloud.google.com/load-balancing/pricing)를 기준으로 해요. 무료 크레딧 적용 여부는 미확인이에요. 운영 기간 종료만으로 과금 자원이 삭제되지는 않으며 사용자가 직접 삭제해요.

이번 구성은 예약 IP를 따로 만들지 않아요. 같은 Service를 유지하는 동안의 주소 보존을 검증하며, Service를 삭제·재생성하거나 클러스터를 재생성한 뒤에도 같은 주소라고 가정하지 않아요.

1. 삭제 전에 현재 Service·외부 IP·forwarding rule·target/health check·연결된 방화벽과 예약 IP 유무를 기록해요. 위 모니터링 수집 연결과 5050 프록시의 회수 순서도 해당 담당자와 확인해요.
2. LB만 회수할 때는 현재 수동 overlay 모드에서 별도 GitOps 변경으로 `service-public.yaml` patch 참조와 파일을 제거하고 GCP active Service가 ClusterIP로 동기화되게 해요. 명세 기반 재생성을 활성화한 뒤라면 먼저 담당자와 요청/재생성 경로·공개 명세·삭제 보호 처리까지 합의해요. 공개 명세를 그대로 두면 LB가 재생성될 수 있고, 공개 필드만 빼면 삭제 보호에 차단돼요. Git 패치 삭제만으로 종료됐다고 판단하지 않아요.
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
| 00:43 KST 팀원 실행 결과 | 성진님이 00:15 수동 승격 완료와 active/preview 동일 selector를 공유했어요. 직접 조회한 현재 상태와 일치해요. 새 preview가 생기는 리허설 PR A에서 외부 URL의 승격 전후 전환과 후속 CI를 함께 확인하기로 했어요. |
| 01:06 KST PR #68 머지 | main `c180dcdeca474bab4c71ca33fe205ad44743b159`에 공개 패치를 반영했어요. |
| 01:10 KST 실제 공개 경로 | 중앙 Application Synced/Healthy·두 source `c180dcd`, Pod 2개 Ready·기존 버전, active UID/ClusterIP/selector 보존·LoadBalancer `34.85.123.113:80`→8080, preview 내부, 외부 health/info HTTP 200·gcp/asia-northeast1·이미지 SHA 일치를 확인했어요. |
| 01:10 KST 실제 GCP LB/방화벽 | target pool 기반 forwarding rule 1개·target HEALTHY, Service 전용 TCP 80 방화벽·health check TCP 10256·우선순위 999, 별도 예약 IP 없음까지 확인했어요. |
| 01:48 KST 팀원 재확인 | 성진님이 공개 주소 20/20 HTTP 200과 세 환경 버전 일치를 [공유했어요](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791650901911239). 이 기록의 직접 GCP 검증과 구분해요. |
| 02:08 KST 명세 계약 정적 검증 | PR #67 공개 Service 테스트 6개·현재 base 호환성 18개 통과. [검증 기록](gcp-public-spec-verification-2026-10-11.md)에 전체 SHA·삭제 보호·예제 차이·미실행 범위를 기록했어요. |
| 남은 공동 검증 | 실제 PR A 최종 파일·선행 코드/실행 버전·활성화 합의, 5050 화면, 새 preview 승격 전후 동일 URL 버전 전환·후속 CI·알림 수신은 아직 미검증이에요. |

기존 Promote 완료는 성진님의 공유 결과와 현재 클러스터 상태를 대조한 기록이에요. 외부 URL에서 승격 전후 전환을 직접 관찰한 결과는 리허설 뒤 별도로 기록해요.
