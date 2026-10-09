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

작업 중인 `argocd/sample-app-gcp.yaml`에 `oneaction.crystal/app: sample-app`, `oneaction.crystal/env: gcp`와 기존 성공/Degraded 구독을 함께 준비했어요. destination은 `name: tokyo-gke`, namespace는 `sample-app`, `CreateNamespace=false`예요. 아직 중앙 EKS에 적용하지 않았어요.

연재님은 env가 `aws/gcp/local`이어야 하며 annotation 누락 시 웹훅이 HTTP 422로 거부된다고 확인했어요. 새 실패 웹훅 [PR #38](https://github.com/Crystal-SBHackathon2026/gitops/pull/38)은 아직 OPEN이고 수신 코드 PR·혜연님 리뷰·배포 → 성진님 트리거/구독 전환 → 성공·Degraded·sync_failed 실연결 검증 순서로 진행해요. 기존 5필드 형식 수신 유지 보고와 실제 GCP 수신 검증은 구분해요.

## 현재 카나리와 다음 검증

[PR #42](https://github.com/Crystal-SBHackathon2026/gitops/pull/42) 이후 공통 분석은 `api-ok`만 사용해요. GKE에 Prometheus를 새로 설치하지 않아요. 환경별 부분 에러율 분석 복원은 렌더러가 실제 측정 백엔드 능력에 맞는 템플릿과 Rollout 참조를 함께 선택하는 방식 등을 성진님·연재님과 별도로 합의해요.

먼저 중앙 EKS egress·운영 인증/갱신·실제 GKE 등록을 맞추고 DB 없는 앱의 내부 응답·환경·버전을 확인해요. 공개 Ingress는 연재님 PR과 출력/RBAC를 검토한 뒤 LB·NEG·health check·주소·TLS 조건을 실제 검증해요. [EKS 연결 요청](gcp-eks-registration-request.md), [GKE 검증 기록](gcp-gke-verification-2026-10-09.md)을 참고해요.
