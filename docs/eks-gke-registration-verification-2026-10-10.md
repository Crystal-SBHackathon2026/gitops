# 중앙 EKS → GKE 인증·등록 검증 기록 — 2026-10-10

GitOps [#55](https://github.com/Crystal-SBHackathon2026/gitops/issues/55)의 EKS 측 기록이에요. [설치 정의와 운영 절차](../argocd/install/eks-gke/README.md)는 이미 적용된 설정을 재현하며 이번 기록 작업에서 다시 배포하지 않았어요. GCP 측의 provider·IAM·GKE RBAC 결과는 [GCP 연결 검증](gcp-integration-verification-2026-10-10.md)과 구분해요.

## 대상과 인증 구성

| 항목 | 확인 값 |
| --- | --- |
| 중앙 EKS | `236550433066` / `ap-northeast-2` / `oneaction` |
| Argo CD | v3.5.4, `argocd` namespace |
| GKE | `crystal-sbh2026-gcp-1009` / `asia-northeast1-a` / `tokyo-gke` |
| GKE API | `https://34.146.143.116` |
| Controller/server 송신 | 실제 Pod의 TLS 검증 HTTPS 조회에서 모두 `43.200.199.19/32`, 해당 private subnet의 NAT 경로와 대조 |
| Google 운영 계정 | `argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com` |
| provider | `projects/19323760731/locations/global/workloadIdentityPools/crystal-eks/providers/oneaction` |
| 등록 Secret | `argocd/cluster-tokyo-gke` |
| 등록 조건 | `name=tokyo-gke`, `namespaces=sample-app`, `clusterResources=false`, `insecure=false` |
| 등록 당시 Secret UID | `879c6f32-6378-40b5-897a-4e3d2cfb27fc` — 생성 관측값이며 재생성 조건이 아님 |
| 공개 CA DER SHA256 | `edc9b0643f0456a2e6e9cba6bb91a223acb0b6acca681e880cb7ea4f351b6a42` |

EKS projected JWT → Google STS → 전용 Google 계정 impersonation → 공식 `argocd-k8s-auth gcp`의 실행 경로를 사용해요. 두 SA subject는 `system:serviceaccount:argocd:argocd-application-controller`와 `system:serviceaccount:argocd:argocd-server`예요. 고정 토큰·서비스 계정 키·운영자 impersonation을 중앙 Argo CD 등록 인증으로 사용하지 않았어요.

## 실제 적용·인증 검증 이력

| 시각(KST) | 검사 | 결과 |
| --- | --- | --- |
| 등록 전 | Controller/server의 실제 송신 주소, Google STS·IAM Credentials API HTTPS | 두 Pod의 송신 주소 일치, Google HTTPS TLS 검증 통과 |
| 등록 전 | 공개 ConfigMap·등록 Secret과 두 워크로드 패치 server dry-run | 스키마·기존 workload 설정 보존 확인 |
| 16:40 | 양쪽 실제 Argo CD Pod에서 GKE 접근과 초기 권한 검사 12개 | `sample-app` Pod/Rollout 조회 HTTP 200, 다른 namespace·노드·namespace UID 조회 HTTP 403, Service create server dry-run HTTP 201 |
| 16:43:16 | 등록 Secret 생성과 Argo CD native cluster DB readback | `tokyo-gke` 대상·CA·exec 설정 확인, 정적 자격증명 없음 |
| 등록 후 | 양쪽 실제 Pod의 Google identity·SA UID·SSAR 42개 | 기대한 Google 이메일과 `sample-app/argocd-deployer` UID 일치, 허용·거부 검사 통과 |
| 17:42:55 | 최초 토큰의 실제 만료와 exec plugin 재발급 | 양쪽 Pod에서 만료된 token HTTP 401 → 새 credential HTTP 200, projected JWT 회전·identity·대상 UID 일치 |
| 17:43 | 기존 AWS 회귀 확인 | 당시 기존 Application spec 유지·Synced/Healthy, AWS 서비스·Secret 공급 회귀 통과 |
| 17:46 | 검증용 EKS API 임시 PC CIDR 제거 | 해당 임시 주소 제거, 최종 EKS Terraform plan No changes |

실제 token 수명은 3600초였고 projected JWT의 요청 수명도 3600초로 설정했어요. 17:42 검사에서 Controller의 이전 token 만료는 17:42:19, 새 만료는 18:42:46 KST였어요. server의 이전 만료는 17:42:26, 새 만료는 18:42:54 KST였어요. 오래된 token이 거부된 후 공식 명령으로 재발급한 credential이 성공했음을 확인했어요. 인증값은 메모리에서만 사용했고 기록에는 시각과 판정만 남겨요.

대상 식별에는 GCP 관리자가 확인한 kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a`와 EKS 운영 계정이 실제 조회한 namespace 안 SA UID `b00980c6-fde1-4178-9c27-22350d595c81`을 사용했어요. 제한된 계정의 kube-system/클러스터 전역 UID 조회는 HTTP 403이며 권한을 추가해 우회하지 않았어요.

## 이번 기록 작업의 검증

GitOps main `d29279adbefd6c846589929b67cc9d7203ca71fb`에서 공개 정의를 정리한 뒤, 최신 main `89fbe7ca7baf73c1a3ce3de57e76ce8b6f5b4c9b`의 앱 이미지·도쿄 수동 승격 변경을 보존하며 충돌 없이 갱신했어요. 실제 EKS 비교와 server dry-run의 최종 검증 시각은 2026-10-10 **20:36:49 KST**예요.

- 공개 ConfigMap의 ADC·CA와 등록 Secret의 exec·TLS·namespace 범위가 현재 적용 값과 일치했어요. JSON 키 순서·공백과 Kubernetes의 volume 기본값은 의미를 기준으로 비교했어요.
- Controller/server는 v3.5.4, 기존 SA를 유지하고 모두 Ready였어요.
- ConfigMap·등록 Secret apply와 두 워크로드 strategic patch의 **server dry-run 4개**를 통과했어요. 현재 workload spec을 바꾸지 않는 정의임을 확인했어요.
- 검사 전후 workload spec·Argo CD Pod UID·Application spec과 공개 WIF 설정이 유지됐어요.
- 실제 apply·persisted patch·Pod 재시작·Application 적용·새 클라우드 리소스 생성은 하지 않았어요.
- 이번 비교에서 GKE token 발급·RBAC·자연 만료 대기는 반복하지 않았어요. 위 이력은 당시 실제 검사 결과이고, 현재 비교는 공개 설정의 일치·재현 검증이에요.

정적 검증과 Python 문법을 확인했고, TLS 해제·정적 token 추가·namespace/cluster 관리 범위 확대·외부 credential source·숨겨진 ConfigMap/Secret data·WIF 외 replica 변경·token 쓰기 허용·JWT audience 변경의 **잘못된 입력 10개를 모두 거부**했어요. 로컬 문서 링크 23개와 PowerShell 명령 블록 3개의 문법도 통과했어요. 복구 명령은 실제 실행하지 않았으며 현재 운영 중인 설치를 제거·재설치하는 시험은 하지 않았어요.

정적 검증은 등록 Secret의 토큰/키 추가, TLS 해제, namespace 범위 확대, 다른 ADC 공급 경로와 WIF 외 workload 변경을 거부해요. 재실행 방법은 [운영 절차](../argocd/install/eks-gke/README.md#현재-상태-확인--적용-없음)를 참고해요.

전체 Secret·kubeconfig snapshot·실제 JWT/access token과 개인 인증값은 Git에 포함하지 않았어요. 과거 실행 증거는 로컬 `.tools/eks-gke-registration-20261010/`의 `registration-contract.json`, `registration-results.json`, `authentication-results.json`, `resume/rbac-results.json`, `renewal-results.json`에 공개 결과로 보관됐어요. 이 로컬 경로는 다른 PC에서 바로 사용할 수 있는 설치 입력이 아니며 재현에 필요한 공개 정의는 위 설치 폴더에 있어요.

## 완료 경계와 후속 확인

EKS 인증 마운트·등록·실제 권한과 자연 만료 후 **exec plugin의 새 credential 발급**은 확인했어요. 실제 Application이 계속 동기화하는 동안의 **client-go 자동 갱신**을 검증한 것으로 확장하지 않아요.

GCP Application 적용 시점·최종 revision은 GitOps 담당과 맞춰요. `tokyo-gke`/`sample-app`, overlay + `analysis/default` 두 sources, `app=sample-app`·`env=gcp`, Notifications 구독과 `CreateNamespace=false`를 보존해요. 이후 다음 항목을 GCP·GitOps 담당과 확인해요.

- 실제 Application 동기화 중 인증 만료/갱신과 Controller/server 접근
- GKE Pod·서비스 `/healthz`·`/api/info`, 환경·버전과 후속 전환
- 중앙 Notifications → Review API의 GCP 배포 기록/baseline

현재 EKS Application의 Healthy 여부는 데모·장애 시험으로 달라질 수 있어요. 과거 회귀 결과나 이번 설정 비교만으로 현재 전체 서비스가 Healthy라고 판정하지 않아요. 로컬 Notifications #19·GCP 외부 주소·앱 배포 완료는 이 이슈의 완료 기준과 별개예요.
