# 중앙 EKS Argo CD의 GKE 등록 인계

## 필요한 이유

GitOps [#37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)에서 GKE 배포 기반을 준비해요. `sample-app-gcp`는 중앙 EKS Argo CD에서 관리하는 모델이고 `destination.name: tokyo-gke`를 재사용해요. 선언된 이름만으로 실제 클러스터 등록·접근·인증이 완료되지는 않아요.

## 대상과 GCP 준비

- 프로젝트 `crystal-sbh2026-gcp-1009`, GKE `tokyo-gke`, `asia-northeast1-a`
- API `https://34.146.143.116`, kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a`
- amd64 노드 1대, `e2-standard-2`, Kubernetes `1.35.8-gke.1225000`
- GCP 준비 파일: [GKE bootstrap](../argocd/install/gke/README.md), 설치와 권한은 GCP 담당이 적용해요.
- 앱 namespace는 `sample-app`이고, 운영 인증 주체는 `argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com`이에요. 별도 `kind: User` RoleBinding으로 기존 Role `argocd-deployer`에 연결했어요. namespace 조회와 현재 Service·Rollout·AnalysisTemplate 쓰기에 제한돼요. 기존 Kubernetes SA와 RoleBinding은 유지해요.
- 설치 후 SA UID는 `b00980c6-fde1-4178-9c27-22350d595c81`예요. EKS 등록 계정으로 이 SA를 읽어 대상 식별을 대조할 수 있어요. SA를 재생성하면 GCP 담당이 UID를 다시 확인해 전달해요.
- GKE API 허용 목록은 기존 PC `58.231.208.183/32`, 변경된 현재 PC `118.235.80.213/32`, EKS 실측 `43.200.199.19/32`예요. 전체 Google Cloud 외부 IP 허용은 꺼져 있고 기존 PC 접근을 보존했어요.
- 운영 종료 목표: 2026-10-12 23:59 KST, 사용자가 수동 삭제해요.

## EKS 담당에게 필요한 작업

- EKS 담당이 Controller/server에서 측정해 전달한 egress `43.200.199.19/32`를 GCP에 반영했어요. EKS 경로의 측정은 담당자 보고이며 이 채팅이 EKS에서 재측정한 결과가 아니에요. 양쪽 Pod에서 GKE TLS/인증을 다시 확인해 주세요.
- EKS OIDC → Google WIF → 전용 Google 계정으로 운영 인증을 연결해 주세요. ADC ConfigMap·projected JWT mount·클러스터 Secret과 실제 만료/갱신 검증은 EKS 담당 범위예요. GCP는 운영 토큰·Google 키를 저장하지 않았어요.
- EKS `argocd`의 등록 이름 `tokyo-gke`·namespace 제한 `sample-app`·`clusterResources: "false"`·CA/TLS 검증을 구성해 주세요. 실제 토큰/키는 Git·Slack·일반 로그에 남기지 않아요.
- UID를 읽는 클러스터 전역 권한은 앱 SA에 주지 않았어요. GCP 운영자 UID 확인과, EKS에서 namespace 안 리소스/UID를 대조하는 방식으로 실제 대상을 확인해 주세요.
- bootstrap과 인증/등록 검증 이후 GCP Application을 적용해 주세요. 현재 작성 중인 변경은 아직 main에 없으므로 적용 파일·revision은 GCP 담당과 맞춰 주세요. `CreateNamespace=false`이고 namespace는 GCP에서 준비해요. `oneaction.crystal/env: gcp`가 기존 구독과 함께 있어야 해요.
- GCP 기존 알림 구독은 GCP Application 파일만 수정해요. 공통 Notifications 템플릿/새 실패 트리거와 카나리 분석은 성진님 담당 변경을 재사용해요.

## GCP 준비 완료 정보 — 2026-10-10

```json
{
  "projectNumber": "19323760731",
  "poolId": "crystal-eks",
  "providerId": "oneaction",
  "serviceAccountEmail": "argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com"
}
```

- 위치는 `global`, issuer는 `https://oidc.eks.ap-northeast-2.amazonaws.com/id/4FAF03630E57E0F50DBEF31F78461274`예요. `google.subject=assertion.sub`이고 `argocd` namespace의 `argocd-application-controller`·`argocd-server` subject 두 개만 provider 조건과 계정 IAM에서 허용해요.
- 기본 provider audience를 사용해요. projected JWT audience는 `https://iam.googleapis.com/projects/19323760731/locations/global/workloadIdentityPools/crystal-eks/providers/oneaction`, external_account ADC audience는 `//iam.googleapis.com/projects/19323760731/locations/global/workloadIdentityPools/crystal-eks/providers/oneaction`이에요.
- 서비스 계정에 두 EKS principal의 `roles/iam.workloadIdentityUser`만 남고 프로젝트 역할·사용자 관리 키는 0개예요. 검증용 15분 조건의 운영자 impersonation 권한은 검사 후 회수했어요.
- 관리자 인증으로 kube-system UID와 기존 Kubernetes SA UID를 재확인했어요. Google 계정 실제 인증/RBAC 26개 검사와 기존 Kubernetes SA 11개 회귀 검사를 통과했어요. 자세한 허용·거부·dry-run 결과는 [WIF 검증 기록](gcp-wif-verification-2026-10-10.md)에 있어요.
- Google token에는 `cloud-platform`과 `userinfo.email` scope가 모두 필요해요. [Argo CD v3.5.4 인증 명령](https://github.com/argoproj/argo-cd/blob/v3.5.4/cmd/argocd-k8s-auth/commands/gcp.go)은 두 scope를 이미 요청해요. 이메일 scope 없이 숫자 uniqueID로 RoleBinding을 우회하는 권한을 추가하지 않았어요.
- 이번 실제 Google 검사는 운영자 impersonation이에요. **EKS projected JWT의 STS 교환·Google impersonation·토큰 갱신·클러스터 등록은 아직 미검증**이에요. 앱 리소스 생성·중앙 Application 적용도 실행하지 않았어요.
- [PR #45](https://github.com/Crystal-SBHackathon2026/gitops/pull/45)는 확인 시 OPEN이에요. 머지 후 GCP Application의 overlay + `analysis/default` 두 소스를 반영하고 적용 파일·revision을 맞춘 뒤 앱을 동기화해 주세요.

## 카나리 오류 조치와 현재 조건

[PR #39](https://github.com/Crystal-SBHackathon2026/gitops/pull/39)의 공통 `error-rate` 지표는 GKE에 없는 Prometheus DNS를 참조해요. 2026-10-09 20:21–20:22 KST에 GKE Rollouts v1.10.0으로 이 지표만 시험해 `count=6`, `consecutiveErrorLimit=6`에서도 7회 연속 DNS 오류 후 AnalysisRun `Error`를 확인했어요. 시험 리소스는 삭제했어요.

이후 성진님이 [PR #42](https://github.com/Crystal-SBHackathon2026/gitops/pull/42)를 머지해 세 환경 공통 분석을 `api-ok`만 사용하도록 바꿨어요. Prometheus 미설치에 따른 GCP 차단 조건은 해소됐어요. 환경별 에러율 복원은 별도 팀 합의로 진행하고 이번 첫 연결에 Prometheus를 새로 설치하지 않아요. 최초 Rollout 배포만으로 후속 카나리 분석을 검증했다고 판단하지 않아요. [검증 기록](gcp-gke-verification-2026-10-09.md)에 과거 실패와 최신 조치를 구분했어요.

## 검증 기준

- EKS 실제 실행 경로에서 TCP 443·CA/호스트 검증·GCP API 인증이 성공해요.
- `tokyo-gke`가 위 GKE를 가리키고 관리 범위가 `sample-app`에 제한돼요. 인증 만료·갱신과 장애 복구 조건을 기록해요.
- 실제 GKE Rollout·Pod Ready·내부 `/healthz`·`/api/info`와 `gcp/asia-northeast1`·이미지/앱 버전까지 확인해요. Synced만으로 완료하지 않아요.
- 중앙 GCP Notifications와 Review API 배포 기록을 확인해요. 외부 LB·후속 카나리·GCP 검토/baseline·전체 환경 gate는 후속 완료 항목과 구분해요.
- 기존 AWS/local Application의 목적지·기존 AWS 알림·ESO Secret 공급에 예상하지 못한 변경이 없어요.

이 문서는 직접 보내지 않은 인계 요청문이에요. 이 채팅은 EKS 등록 Secret·Controller·IAM·네트워크를 수정하지 않아요.
