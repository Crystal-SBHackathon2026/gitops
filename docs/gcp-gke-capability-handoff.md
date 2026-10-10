# GKE 실측 정보와 렌더러 능력표 인계

[이슈 #37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37), 연재님의 [20:46 KST 요청](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791546368057559)에 따른 인계예요. 2026-10-09 20:55 KST 별도 GKE kubeconfig와 GCP cluster API로 읽기 전용 실측했어요. 프로젝트는 `crystal-sbh2026-gcp-1009`, 클러스터는 `tokyo-gke`, `asia-northeast1-a`예요.

| 요청 항목 | 직접 확인한 사실 | 아직 확인하지 않은 범위 |
| --- | --- | --- |
| 네트워크 | VPC-native `useIpAliases=true`, VPC `crystal-gke`, subnet `tokyo-gke` | 공개 Ingress·LB·NEG·health check의 실제 앱 동작 |
| GKE Ingress 기반 | HttpLoadBalancing 활성, `backendconfigs.cloud.google.com` CRD 존재 | 연재님 렌더러 출력과 Controller 연결·공개 응답 |
| 내부 Ingress | 현재 첫 연결/후속 렌더러는 공개 Ingress 계획 | proxy-only subnet·전용 방화벽 조건은 내부 Ingress를 선택할 경우 별도 확인 |
| 노드 | amd64 노드 1대 Ready, `e2-standard-2` | 증설·arm64 지원은 이번 범위가 아님 |
| 저장소 | 기본 `standard-rwo`, provisioner `pd.csi.storage.gke.io`, `WaitForFirstConsumer` | 앱 PVC 0개, 실제 Pod와 PVC Bound·데이터 보존은 미검증 |
| DB·버킷 | 첫 앱은 DB 없는 sample-app, 이번 작업에서 Cloud SQL·앱 버킷을 생성하지 않음 | DB/버킷 계획은 현재 범위에 없음. 새 요구는 비용·규모 승인 후 검증 |
| Secret | `sample-app` Secret 0개, ExternalSecret CRD 없음. 이 앱용 ESO/Secret Manager/수동 Secret 공급을 구성하지 않음 | Secret이 필요한 앱은 공급 방식 합의·권한·실제 공급 확인 전 지원 완료로 표시하지 않음 |
| TLS·DNS | GKE API의 CA/TLS 검증은 통과한 기존 실측 | 앱 공개 도메인·인증서 방식 미정. API TLS와 앱 HTTPS를 구분 |

기반 존재만으로 공개 Ingress·PVC·DB·Secret을 `verified: true`로 올리지 않아요. 네트워크/노드처럼 직접 확인한 사실은 전달하되 능력표의 배포 지원 검증은 각각 필요한 실제 동작 확인까지 연재님과 맞춰요. 새 PVC·DB·LB는 이번 읽기 전용 확인에서 생성하지 않았어요.

## Application과 알림 계약

성진님의 [PR #51](https://github.com/Crystal-SBHackathon2026/gitops/pull/51)이 `argocd/sample-app-gcp.yaml`에 app=sample-app/env=gcp와 성공·Degraded·sync_failed 구독을 준비했어요. destination은 `name: tokyo-gke`, namespace는 `sample-app`, `CreateNamespace=false`이고 overlay + `analysis/default` 두 source를 유지해요. #37의 중복 Application 변경은 제외했어요. 아직 실제 Application 적용·앱 배포는 검증하지 않았어요.

연재님은 env가 `aws/gcp/local`이어야 하며 annotation 누락 시 웹훅이 HTTP 422로 거부된다고 확인했어요. 수신 코드 review-service #53과 gitops #38은 머지됐고, 성진님의 #49·#50이 트리거 활성화와 다중 source revision/oncePer 수정을 반영했어요. GCP는 중앙 EKS Notifications의 기존 내부 Review API 경로를 재사용해요. 로컬 외부 수신 경로 #19와 별개이며 실제 GCP 알림·baseline 확인은 남아 있어요.

## 현재 배포 전략과 다음 검증

[PR #45](https://github.com/Crystal-SBHackathon2026/gitops/pull/45)는 AWS에 `analysis/prometheus`, 로컬·GCP에 `analysis/default`를 선택해요. [PR #48](https://github.com/Crystal-SBHackathon2026/gitops/pull/48)의 GCP 데모 overlay는 블루그린이고 active/preview Service 두 개를 사용해요. 현재 전환 전후 Analysis는 없고 readiness·progressDeadlineSeconds=60 조건을 사용해요. AnalysisTemplate 배포와 분석 실행은 구분하고 GKE Prometheus는 설치하지 않아요.

2026-10-10 중앙 EKS 실측 egress `43.200.199.19/32`를 GKE API에 허용하고, EKS OIDC의 Controller/server subject 두 개만 허용하는 Google WIF·전용 Google 서비스 계정 IAM·namespace RoleBinding을 준비했어요. 실제 Google 계정 RBAC 26개 검사와 기존 Kubernetes SA 회귀 11개를 통과했어요. 이 인증은 **클러스터 운영 연결용**이며 앱 Secret 공급이 구성됐다는 뜻은 아니에요.

EKS 담당은 실제 Controller/server의 WIF 교환·TLS·동일 SA UID·제한된 권한·클러스터 등록과 만료 후 재발급 성공을 인계했어요. 앱 트래픽의 client-go 자동 갱신은 미검증이에요. #51은 18:39:38 KST 머지됐고, 다음은 성진님의 Application 적용과 GCP 담당의 첫 DB 없는 앱 내부 응답·환경·버전/알림/baseline 확인이에요. 공개 Ingress는 연재님 출력과 RBAC를 별도로 검토한 뒤 LB·NEG·health check·주소·TLS 조건을 실제 검증해요. [최신 연결 검증](gcp-integration-verification-2026-10-10.md), [EKS 연결 인계](gcp-eks-registration-request.md), [오전 WIF 기록](gcp-wif-verification-2026-10-10.md)을 참고해요.
