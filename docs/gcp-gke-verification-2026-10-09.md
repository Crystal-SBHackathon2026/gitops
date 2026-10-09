# GCP GKE 배포 기반 검증 — 2026-10-09

[이슈 #37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 GCP bootstrap 검증 기록이에요. GKE 실행 기반은 준비됐지만 중앙 Argo CD 연결과 앱 배포 완료는 아직 확인하지 않았어요.

## 대상과 변경 범위

- 프로젝트 `crystal-sbh2026-gcp-1009`, GKE `tokyo-gke`, `asia-northeast1-a`, API `https://34.146.143.116`
- kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a`, Kubernetes `1.35.8-gke.1225000`, amd64 `e2-standard-2` 노드 1대
- 작업 브랜치 `feat/37-gcp-gke-connection`, 최신 main `c89c9f0bd7a1dabbfa760086e9b244e342edfbe0`의 PR #42를 반영했어요. 20:31 KST 인증/RBAC 재검증과 아래 카나리 시험은 `4e2232c` 기준이며, `a24adc9` 기준 GCP 출력으로 20:35 KST 인증/RBAC 10개 검사를 다시 통과했어요. #42 기준 출력으로 20:59 KST 인증/RBAC 10개 검사와 아래 최신 정적 검증도 통과했어요.
- GKE에 `argo-rollouts`·`sample-app` namespace, Rollouts v1.10.0·CRD 5개와 앱 SA/Role/RoleBinding을 설치했어요. [설치·검증 스크립트](../argocd/install/gke/README.md)로 별도 kubeconfig와 API/UID를 확인해요.
- 기존 checkout·다른 작업 브랜치·EKS 리소스·공통 `apps/` 및 Notifications 구현은 변경하지 않았어요. GCP Application 파일은 연결 준비 상태이며 EKS에 적용하지 않았어요.

## 통과한 검증

| 검증 | 직접 확인한 결과 |
| --- | --- |
| 대상 보호 | 잘못된 kube-system UID 입력 시 변경 전 중단했어요. 모든 Kubernetes 명령은 별도 GKE kubeconfig를 사용해요. |
| 설치 원본 | 공식 v1.10.0 설치 파일의 SHA256이 고정값과 일치했어요. client dry-run을 통과했어요. |
| 실행 기반 | `quay.io/argoproj/argo-rollouts:v1.10.0` Controller 1개 Ready, CRD 5개 Established를 확인했어요. |
| 리소스 | Controller requests `100m/128Mi`, limits `500m/256Mi`, 원본 ephemeral-storage limit 유지와 적용 상태 diff 0을 확인했어요. |
| 실제 앱 SA 인증 | 15분 TokenRequest로 CA/TLS 검증을 포함한 실제 HTTP 검사를 진행했어요. 토큰은 메모리에서만 사용하고 출력·저장하지 않았어요. |
| 허용한 조회 2개 | `sample-app` Pod·Rollout 조회가 HTTP 200이었어요. |
| 차단한 작업 5개 | kube-system Pod·클러스터 Node 조회, SA 토큰 발급, Secret 쓰기·RoleBinding 권한 상승이 HTTP 403이었어요. 쓰기 검사는 server dry-run이에요. |
| 현재 GCP 출력 3개 | 최신 main의 Service·AnalysisTemplate·Rollout을 앱 SA로 server dry-run create해 HTTP 201을 확인했어요. 실제 앱 리소스는 만들지 않았어요. |
| 정적 검사 | PowerShell 구문·Python 구문/기존 compile·변경 YAML 5개·bootstrap 5개 리소스·3개 환경 출력·GCP Application 계약·로컬 문서 링크 17개·`git diff --check`를 통과했어요. |

20:14 KST 최초 bootstrap 검증과 최신 main 반영 후 20:31 KST 재검증에서 인증/RBAC 10개 검사를 모두 통과했어요. CRD는 `rollouts`·`analysistemplates`·`analysisruns`·`experiments`·`clusteranalysistemplates`예요. 정적 검사의 최초 임시 검사 코드가 analysis step 위치를 잘못 가정해 실패했지만, 실제 analysis 항목을 찾아 검사하도록 고쳐 최종 검사를 통과했어요. 배포 코드의 실패가 아니며 아래 실측 카나리 오류와 구분해요.

## 실패를 확인한 카나리 선행 조건

[PR #39](https://github.com/Crystal-SBHackathon2026/gitops/pull/39)가 추가한 공통 Prometheus `error-rate` 지표만 추출해 임시 `AnalysisRun/gcp-prometheus-prereq-check`를 GKE에서 실행했어요. 앱 배포나 공통 지표 수정 없이 측정 백엔드 접근을 확인한 시험이에요.

- 실행 시간: 20:21:16–20:22:16 KST
- 설정: `interval: 10s`, `count: 6`, `consecutiveErrorLimit: 6`
- 대상: `monitoring-kube-prometheus-prometheus.monitoring.svc.cluster.local:9090`
- 결과: GKE에 해당 Prometheus가 없어 DNS `no such host`가 7회 연속 발생했고 AnalysisRun이 `Error`로 종료됐어요.
- Controller 상태 메시지: `Metric "error-rate" assessed Error due to consecutiveErrors (7) > consecutiveErrorLimit (6)`

`count`와 오류 한도를 같게 두면 측정 오류로 중단되지 않는다는 조건은 이 실측에서 성립하지 않았어요. 당시에는 환경별 지표 구성을 선행 조건으로 남겼고 아래 PR #42가 공통 지표를 제거해 첫 GCP 연결의 차단 조건을 해소했어요. 로컬에서의 영향은 이번에 직접 검증하지 않았어요.

추가 확인한 [PR #41](https://github.com/Crystal-SBHackathon2026/gitops/pull/41)과 PR #40은 현재 MERGED예요. #41의 초기 측정 지연·횟수 보완은 이후 #42의 지표 제거로 현재 분석에 적용되지 않아요. #40의 변경 대상은 AWS ServiceMonitor이며 GCP bootstrap과 겹치지 않아요.

20:24 KST 시험 AnalysisRun을 삭제한 뒤 `sample-app`에 Rollout·AnalysisTemplate·AnalysisRun·Service가 없음을 확인했어요. 운영 토큰·앱 Secret·DB·공개 LB를 생성하지 않았어요.

## 최신 팀 조치 — Prometheus 차단 해소

- 성진님의 20:52 KST [답장](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791546756650999)과 [PR #42](https://github.com/Crystal-SBHackathon2026/gitops/pull/42) 머지를 확인했어요. 공통 `error-rate`와 canary-hash 인자를 제거했고 현재 세 환경은 `api-ok`만 사용해요.
- 로컬의 동일 DNS 오류·Degraded/abort와 수정 후 abort 해제·HTTP 200, AWS Healthy 3/3은 성진님의 실행 보고예요. 이 채팅의 GKE 직접 실측과 구분해요.
- GCP에 Prometheus를 추가하는 것은 현재 첫 연결의 선행 조건이 아니에요. 부분 에러율 분석 복원은 성진님·연재님의 환경별 렌더링 방식 등 팀 합의가 필요하고 이번 이슈에서 공통 구현을 중복 수정하지 않아요.
- 직접 재검증: AWS·local·GCP 렌더링의 지표가 `api-ok` 하나이고 Prometheus provider·canary-hash 인자·끊어진 AnalysisTemplate 참조가 없어요. GCP의 app/env annotation·기존 구독·목적지 계약, 로컬 문서 링크 21개와 `git diff --check`를 통과했어요. 실제 GCP 앱/카나리는 실행하지 않았어요.
- 연재님의 20:46 KST [답장](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791546368057559)은 GKE 공개 Ingress 렌더러 준비 중·PR 전이라고 했어요. 요청한 환경 정보는 [능력표 인계](gcp-gke-capability-handoff.md)에 직접 실측과 미확인을 구분해 기록해요.

## 아직 확인하지 않은 연결과 완료 조건

- EKS Argo CD의 실제 GKE API 송신 IP와 운영 인증 공급·만료·갱신 방식은 EKS 담당 확인을 기다려요. [EKS 연결 요청](gcp-eks-registration-request.md)에 대상·권한·검증 기준을 정리했어요.
- 중앙 등록 이름 `tokyo-gke`, namespace `sample-app`, `clusterResources: "false"`와 실제 대상 SA UID 대조를 확인해야 해요. SA UID는 `b00980c6-fde1-4178-9c27-22350d595c81`예요.
- 중앙 연결 이후 실제 GitOps revision·GKE Pod Ready·Service `/healthz`와 `/api/info` 응답·`gcp/asia-northeast1`·앱 버전을 확인해야 해요. `api-ok` 후속 카나리 실행도 별도로 확인해요.
- Notifications 수신과 GCP 검토 기록 매칭·baseline 저장은 아직 검증하지 않았어요. 공통 실패 트리거 PR #38과 기존 구독 전환은 성진님과 맞춰요.
- 현재 GCP 렌더러 출력은 공개 Ingress가 없어요. 연재님과 Ingress·NEG/health check·공개 LB를 연결하는 후속 작업을 맞춰야 해요.
- 이번 검증은 명세부터 GitOps·실제 서비스·환경별 baseline까지의 전체 흐름 성공을 의미하지 않아요. 이슈 #37의 중앙 연결·실제 앱 배포 완료 조건은 남아 있어요.

운영 종료 목표는 2026-10-12 23:59 KST이고 사용자가 직접 삭제해요. 10월 13일 00:00의 예약은 읽기 전용 종료 점검이에요.
