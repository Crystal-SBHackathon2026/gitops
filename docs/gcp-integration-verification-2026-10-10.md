# 중앙 EKS 등록 이후 GCP 연결 검증

[이슈 #37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 오후 검증 결과예요. EKS 담당의 실제 등록·인증 인계와 이 채팅이 GCP에서 직접 실행한 검사를 구분해요. 오전 26/11개 검사는 [오전 WIF 기록](gcp-wif-verification-2026-10-10.md)에 보존해요.

## 최신 GitOps 구성과 변경 소유권

- #45는 환경별 분석을 두 Application source로 분리했고 #48은 GCP 데모를 블루그린으로 바꿨어요. #38·#49·#50은 새 알림 계약·활성화·다중 source revision/oncePer 보완을 main에 반영했어요.
- 성진님의 [PR #51](https://github.com/Crystal-SBHackathon2026/gitops/pull/51)은 2026-10-10 18:39:38 KST에 머지됐어요. `destination.name=tokyo-gke`, namespace=`sample-app`, app=sample-app/env=gcp, 성공·Degraded·sync_failed 구독, `CreateNamespace=false`와 두 source를 유지해요.
- #37의 중복 Application 수정은 제외하고 #51을 재사용해요. #37은 GKE bootstrap·WIF/IAM/RBAC·검증 도구·운영 문서에 집중해요. 성진님이 최종 main revision으로 Application 적용을 진행하고 GCP 담당이 실제 대상·앱 응답을 검증해요.
- 현재 GCP 네 리소스는 Service `sample-app`·`sample-app-preview`, Rollout `sample-app`, AnalysisTemplate `sample-app-health`예요. source는 `apps/sample-app/overlays/gcp`와 `apps/sample-app/analysis/default`예요.
- 블루그린은 autoPromotionEnabled=true, autoPromotionSeconds=30, scaleDownDelaySeconds=30이며 전환 전후 Analysis는 없어요. readiness·progressDeadlineSeconds=60 조건과 AnalysisTemplate 존재를 분석 실행 성공으로 혼동하지 않아요. 후속 preview 응답 분석은 성진님·연재님과 별도 변경으로 연결해요.

## EKS 담당의 실제 운영 경로 인계

근거는 EKS 담당의 17:16 KST 등록 인계와 17:42 KST `renewal-results.json` 공개 결과예요. 아래는 이 채팅이 EKS에서 실행한 검사가 아니에요.

- 실제 등록 시각 16:43:16 KST, Secret `argocd/cluster-tokyo-gke`, UID `879c6f32-6378-40b5-897a-4e3d2cfb27fc`예요. 실제 Argo CD 클러스터 DB에서 endpoint·CA·exec 인증 설정을 대조했어요.
- 관리 범위는 namespaces=`sample-app`, clusterResources=false, insecure=false예요. 두 Argo Pod 실측 egress는 `43.200.199.19/32`예요.
- GKE CA DER SHA256은 `edc9b0643f0456a2e6e9cba6bb91a223acb0b6acca681e880cb7ea4f351b6a42`이고 두 Pod가 아래 GKE SA UID를 HTTP 200으로 확인했어요.
- projected JWT → Google STS → 전용 Google 계정 impersonation → 공식 `argocd-k8s-auth v3.5.4 gcp`를 사용했어요. cloud-platform·userinfo.email scope, JWT/access token 각각 3600초예요.
- Google identity 확인·GKE Pod/Rollout 조회·Service server dry-run과 실제 SSAR 42개·초기 HTTP 권한 검사 12개를 통과했다고 인계했어요.
- 17:42:55 KST 기록은 실제 최초 토큰 만료·projected JWT 교체·양쪽 Pod 공식 exec plugin 재발급 성공을 확인해요. `productionClientGoAutomaticRefreshWithApplicationTrafficVerified=false`이며 **앱 트래픽에서의 client-go 자동 갱신은 미검증**이에요.
- EKS ConfigMap·JWT/ADC mount·클러스터 등록의 설치 설정 영속화는 EKS 담당의 별도 검토/PR 범위예요. #37에 EKS 리소스 변경을 추가하지 않아요.

## GCP 직접 재검증

최종 readback 시각은 2026-10-10 18:47:28 KST예요. Google 계정 검사는 운영자 impersonation이고, 위 EKS JWT 교환 검사와 구분해요. 검증 토큰은 메모리에만 사용하고 앱 쓰기는 server dry-run으로 확인했어요.

| 항목 | 직접 확인 결과 |
| --- | --- |
| 대상 | 프로젝트 `crystal-sbh2026-gcp-1009` / 번호 `19323760731`, `asia-northeast1-a/tokyo-gke`, API `https://34.146.143.116` |
| 클러스터 식별 | 관리자 kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a` |
| 앱 namespace | `sample-app` Active, UID `a973059f-62e9-4146-8fe2-1a51b883d16d` |
| 배포 SA 식별 | `sample-app/argocd-deployer`, UID `b00980c6-fde1-4178-9c27-22350d595c81` |
| 실행 기반 | 클러스터 RUNNING, 노드 1대 Ready, Rollouts v1.10.0 availableReplicas=1, CRD 5개 Established |
| Google 계정 RBAC | 27개 통과: 조회 3개·HTTP 403 거부 5개·SSAR 허용 12개/거부 3개·네 리소스 dry-run 4개 |
| 기존 Kubernetes SA | 12개 회귀 검사 통과: 조회 3개·HTTP 403 거부 5개·네 리소스 dry-run 4개 |
| 임시 권한 회수 | 15분 조건의 운영자 workloadIdentityUser binding 제거, 최종 IAM은 두 EKS subject만 허용 |
| WIF/IAM | pool/provider ACTIVE, issuer·mapping·두 subject 조건 일치, Google 계정 프로젝트 역할 0개·사용자 관리 키 0개 |
| 앱 리소스 | Pod·Service·Rollout·AnalysisTemplate·AnalysisRun·Secret·Ingress·PVC 모두 0개 |

작업 PC 송신 IP는 독립 HTTPS 서비스 두 곳에서 `118.235.82.91`로 실측했어요. 이전 PC 두 CIDR과 EKS CIDR을 보존해 추가했고 update operation DONE·현재 허용 목록·실제 API 접근을 확인했어요. 현재 네 CIDR은 `58.231.208.183/32`, `118.235.80.213/32`, `118.235.82.91/32`, `43.200.199.19/32`예요. 전체 Google 외부 IP 허용은 비활성이에요. 기존 PC 허용을 언제 회수할지는 운영자와 별도로 맞춰요.

Google 임시 권한 추가 직후 첫 발급 요청은 HTTP 403이었어요. IAM 반영을 기다린 재시도에서 27개가 통과했고 임시 binding 회수 후 최종 정책을 재확인했어요. 초기 정적 검사 도구는 AWS/local Ingress를 빠뜨린 리소스 개수 조건으로 실패했어요. 실제 네 리소스로 조건을 수정한 최종 정적 검사는 통과했고 AWS/local 매니페스트는 변경하지 않았어요.

## 정적 검증과 남은 실제 배포 확인

- AWS·local·GCP의 두 source를 각각 렌더링해 중복 리소스·환경 값·이미지·분석 선택을 확인했어요. AWS는 api-ok/error-rate 카나리, local은 api-ok 카나리, GCP는 두 Service 블루그린이에요. #51의 목적지·namespace·annotation·세 구독·CreateNamespace=false도 확인했어요.
- [Verify-GkeBootstrap.py](../argocd/install/gke/Verify-GkeBootstrap.py)는 `--rendered-manifests`로 두 source를 합친 입력을 받아요. 기존 `--rendered-overlay`도 별칭으로 유지해요. 리소스 중복·namespace·블루그린 Service 참조를 검사하며 기존 제한된 Role은 확장하지 않았어요.
- 실제 Application 적용·첫 앱 동기화·Pod Ready·내부 `/healthz`와 `/api/info`·environment=gcp/region=asia-northeast1·이미지 SHA/앱 버전 확인은 남아 있어요. 두 source의 revision도 기록해요.
- GCP Notifications 수신·검토 기록 연결·baseline과 앱 동기화 트래픽의 자동 인증 갱신을 후속 검증해요. 실패 이벤트가 실제 발생하지 않았다면 검증 완료로 표시하지 않아요.
- 공개 Ingress/LB·PVC·DB·Secret·마이그레이션과 전체 활성 환경 gate는 별도 완료 기준이에요. 현재 Role은 Service·Rollout·AnalysisTemplate 쓰기만 허용하므로 새 출력이 필요하면 RBAC·비용·담당 범위를 먼저 맞춰요.
- PR 생성·push·머지와 실제 Application 적용은 이 검증에서 실행하지 않았어요. Synced 표시만으로 GCP 연결 완료를 판정하지 않아요.
