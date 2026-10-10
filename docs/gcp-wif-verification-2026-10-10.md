# GCP WIF 준비와 실제 Google 계정 RBAC 검증

[이슈 #37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 중앙 EKS Argo CD 연결 준비 결과예요. 2026-10-10 10:32 KST에 실제 Google 계정 인증/RBAC 검사를 통과했어요. GCP만 변경했고 EKS 등록·앱 배포는 아직 실행하지 않았어요.

## 대상·API 허용 목록

- 프로젝트 `crystal-sbh2026-gcp-1009` / 번호 `19323760731`, GKE `tokyo-gke` / `asia-northeast1-a`, API `https://34.146.143.116`
- 관리자 인증으로 kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a`와 Kubernetes SA UID `b00980c6-fde1-4178-9c27-22350d595c81`를 재확인했어요. 앱 계정에 kube-system UID 조회 권한을 추가하지 않았어요.
- API 허용: `58.231.208.183/32`(기존 PC 보존), `118.235.80.213/32`(변경된 현재 PC), `43.200.199.19/32`(EKS 담당 실측). authorized networks 활성, 전체 Google 외부 IP 허용 비활성이에요.
- 작업 PC의 송신 IP가 바뀌어 처음 관리자 UID 조회는 타임아웃이었어요. 독립적인 HTTPS 서비스 두 곳에서 현재 IP를 대조하고 기존 PC·EKS CIDR을 함께 보존해 접근을 복구했어요. 네트워크 변경 operation `operation-1791595295958-92f64c78-da68-4d5f-a90a-2508adc17364`의 DONE과 클러스터 RUNNING을 확인했어요.

## WIF·IAM·RBAC 최종 설정

- global pool `crystal-eks`, provider `oneaction` 모두 ACTIVE예요. 공개 설정은 [federation.json](../argocd/install/gke/federation.json), 재현 스크립트는 [Prepare-GkeFederation.ps1](../argocd/install/gke/Prepare-GkeFederation.ps1)이에요.
- EKS issuer는 `https://oidc.eks.ap-northeast-2.amazonaws.com/id/4FAF03630E57E0F50DBEF31F78461274`이며 공개 OIDC discovery/JWKS의 issuer를 대조했어요. `google.subject=assertion.sub`이고 아래 subject 두 개만 provider 조건과 계정 IAM에서 허용해요.
  - `system:serviceaccount:argocd:argocd-application-controller`
  - `system:serviceaccount:argocd:argocd-server`
- 전용 계정은 `argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com`이에요. 각 EKS principal에 `roles/iam.workloadIdentityUser`만 부여했어요. 전용 계정의 프로젝트 역할은 0개, 사용자 관리 키도 0개예요.
- `sample-app/argocd-google-deployer` RoleBinding은 Google 계정 이메일을 `kind: User`로 기존 Role `argocd-deployer`에 연결해요. 기존 Kubernetes SA/RoleBinding은 보존했어요.
- 운영자에게 서비스 계정 한 개에만 15분 만료 조건의 `roles/iam.workloadIdentityUser`를 임시 부여해 실제 Google 인증을 검사했어요. 검사 후 이 binding을 제거하고 최종 IAM에 두 EKS principal만 남는지 다시 확인했어요. TokenCreator·프로젝트 Editor·container.admin/developer를 추가하지 않았어요.

## 실제 인증 검사 결과

관리자 kubeconfig를 사용하는 `kubectl --as`만으로 판정하지 않았어요. Google IAM Credentials API에서 받은 15분 계정 토큰을 메모리에만 유지하고, 클러스터 CA와 호스트를 검증하는 HTTPS 요청으로 검사했어요. 현재 main #42 기준 GCP의 Service·AnalysisTemplate·Rollout 출력을 사용했어요.

| 검사 | 실제 결과 |
| --- | --- |
| sample-app Pod·Rollout·기존 SA UID 조회 3개 | HTTP 200, 대상 SA UID 일치 |
| kube-system Pod·노드 조회, SA token 발급, Secret 쓰기, RoleBinding 권한 상승 5개 | HTTP 403 |
| Service·Rollout·AnalysisTemplate의 create/update/patch/delete 12개 | 실제 Google SelfSubjectAccessReview `allowed=true` |
| namespace 생성·ClusterRole 생성·Secret patch 3개 | 실제 Google SelfSubjectAccessReview `allowed=false` |
| 현재 앱 Service·AnalysisTemplate·Rollout create 3개 | server dry-run HTTP 201 |

Google 계정 26개 검사와 기존 Kubernetes SA 11개 회귀 검사를 모두 통과했어요. SelfSubjectAccessReview의 HTTP 201은 요청이 처리됐다는 뜻이며 권한 허용 여부는 `allowed`로 판정했어요. Rollouts v1.10.0 Controller availableReplicas=1·CRD 5개 Established도 확인했어요. sample-app Pod·Service·Rollout·AnalysisTemplate·AnalysisRun·Secret은 최종 조회에서 모두 0개예요.

처음 운영자는 서비스 계정의 getAccessToken 권한이 없어 Google API HTTP 403이었어요. 임시 권한 부여 후 정책 반영을 기다려 발급이 성공했어요. 이후 `cloud-platform`만 포함한 토큰은 GKE에서 숫자 uniqueID로 식별돼 이메일 RoleBinding 검사에 HTTP 403이었어요. `userinfo.email`을 함께 요청한 토큰은 HTTP 200이며 26개 검사를 통과했어요. [GKE 인증 문서](https://docs.cloud.google.com/kubernetes-engine/docs/how-to/api-server-authentication#authenticate_users)와 [Argo CD v3.5.4 소스](https://github.com/argoproj/argo-cd/blob/v3.5.4/cmd/argocd-k8s-auth/commands/gcp.go)가 같은 scope 조건을 설명해요.

## 오전 검사 당시 남은 검증과 인계

아래는 10:32 KST 당시 기록이에요. 이후 #45 머지·#48 블루그린·EKS 실제 등록/만료 후 재발급·#51과 최신 GCP 검사는 [오후 연결 검증 기록](gcp-integration-verification-2026-10-10.md)에 구분해요. 오전의 26/11개 결과와 허용 목록을 현재 값으로 덮어쓰지 않아요.

- 이 결과의 credential source는 **운영자 impersonation**이에요. EKS projected JWT → STS → Google impersonation·3600초 만료/갱신은 EKS 담당의 실제 Pod에서 별도로 검증해야 해요. 토큰·키·개인 credential은 전달하지 않아요.
- EKS에서 API TLS/인증·동일 SA UID·허용/거부·갱신을 확인하고 `tokyo-gke`, namespaces=`sample-app`, clusterResources=false로 등록해요. Controller/server mount 적용 시점은 중앙 Argo CD 담당과 맞춰요.
- 성진님 [PR #45](https://github.com/Crystal-SBHackathon2026/gitops/pull/45)는 확인 시 OPEN이에요. 머지 후 overlay + `analysis/default` 두 소스와 기존 app/env·구독·CreateNamespace=false를 맞추고 GCP Application을 적용해요.
- GKE 실제 Pod Ready·내부 HTTP 200·gcp/asia-northeast1·이미지/버전, 후속 카나리·Notifications/Review API 기록·baseline은 아직 미검증이에요. 공개 Ingress는 연재님 렌더러 후속과 연결해요. 새 클러스터·DB·LB·앱 Secret은 이번 준비에서 생성하지 않았어요.
- [공개 인계 정보와 EKS 후속 기준](gcp-eks-registration-request.md)을 참고해요. PR 작성·push·머지는 별도 승인 전이에요.
