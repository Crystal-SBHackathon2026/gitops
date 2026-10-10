# 중앙 EKS Argo CD의 GKE 등록 인계

## 필요한 이유

GitOps [#37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 GKE 배포 기반과 중앙 EKS 등록 인계예요. `sample-app-gcp`는 중앙 EKS Argo CD에서 관리하고 `destination.name: tokyo-gke`를 재사용해요. EKS 담당이 2026-10-10 16:43 KST 등록·실제 Pod 접근을 완료했고 17:42 KST 만료 후 재발급 결과를 전달했어요. 실제 앱 배포 완료와는 구분해요.

## 대상과 GCP 준비

- 프로젝트 `crystal-sbh2026-gcp-1009`, GKE `tokyo-gke`, `asia-northeast1-a`
- API `https://34.146.143.116`, kube-system UID `c249c507-6262-4b06-be44-ab019fa3256a`
- amd64 노드 1대, `e2-standard-2`, Kubernetes `1.35.8-gke.1225000`
- GCP 준비 파일: [GKE bootstrap](../argocd/install/gke/README.md), 설치와 권한은 GCP 담당이 적용해요.
- 앱 namespace는 `sample-app`이고, 운영 인증 주체는 `argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com`이에요. 별도 `kind: User` RoleBinding으로 기존 Role `argocd-deployer`에 연결했어요. namespace 조회와 현재 Service·Rollout·AnalysisTemplate 쓰기에 제한돼요. 기존 Kubernetes SA와 RoleBinding은 유지해요.
- 설치 후 SA UID는 `b00980c6-fde1-4178-9c27-22350d595c81`예요. EKS 등록 계정으로 이 SA를 읽어 대상 식별을 대조할 수 있어요. SA를 재생성하면 GCP 담당이 UID를 다시 확인해 전달해요.
- GKE API 허용 목록은 기존 PC `58.231.208.183/32`, 오전 PC `118.235.80.213/32`, 오후 실측 PC `118.235.82.91/32`, EKS 실측 `43.200.199.19/32`예요. 오후 PC 변경 때 기존 세 CIDR을 보존했어요. 전체 Google Cloud 외부 IP 허용은 꺼져 있어요. PC IP 변경은 EKS 송신 경로 변경과 별개예요.
- 운영 종료 목표: 2026-10-12 23:59 KST, 사용자가 수동 삭제해요.

## EKS 담당의 완료 인계와 소유 범위

- EKS 담당은 실제 Controller/server egress `43.200.199.19/32`, GKE TLS/CA·동일 SA UID·Google identity·제한된 권한을 검증했다고 인계했어요. 이 채팅이 EKS에서 실행한 검사가 아니에요.
- 등록 Secret은 `argocd/cluster-tokyo-gke`, name=`tokyo-gke`, namespaces=`sample-app`, clusterResources=false, insecure=false예요. Argo CD 실제 클러스터 DB readback도 EKS 담당이 확인했어요.
- 운영 경로는 EKS projected JWT → Google STS → 전용 Google 계정 impersonation → 공식 `argocd-k8s-auth v3.5.4 gcp`예요. 두 scope는 cloud-platform·userinfo.email이고 JWT/access token 수명은 각각 3600초예요.
- EKS 담당은 17:42 KST 실제 최초 토큰 만료·projected JWT 교체·양쪽 Pod의 공식 exec plugin 재발급 성공을 기록했어요. **앱 트래픽에서 client-go 자동 갱신은 미검증**이에요.
- ADC ConfigMap·projected JWT mount·등록 Secret 운영과 설치 설정으로의 영속화는 EKS 담당의 별도 검토/PR 범위예요. [EKS 인증·등록 정의와 복구 절차](../argocd/install/eks-gke/README.md), [EKS 실제 검증 기록](eks-gke-registration-verification-2026-10-10.md)을 참고해요. GCP는 EKS 리소스를 수정하지 않고 토큰·키를 전달하지 않아요.
- 앱 계정에는 클러스터 전역 UID 조회 권한을 추가하지 않았어요. GCP 관리자 kube-system UID와 제한된 계정의 namespace 안 SA UID를 대조해요.

## Application 적용 인계

- 성진님의 [PR #51](https://github.com/Crystal-SBHackathon2026/gitops/pull/51)이 app=sample-app/env=gcp·성공/Degraded/sync_failed 구독·CreateNamespace=false를 준비했어요. overlay + `analysis/default` 두 source를 유지하고 #37에서 동일 파일을 중복 수정하지 않아요.
- GCP에서 `sample-app` namespace가 Active임을 직접 확인했어요. #51은 18:39:38 KST 머지됐으므로 최종 main revision을 맞춘 뒤 성진님이 Application 적용을 진행해요.
- GCP 알림은 중앙 EKS Notifications의 `http://platform.platform.svc.cluster.local:8080/webhooks/argocd` 경로를 재사용해요. 로컬 외부 수신 보완 #19와 별개예요. 공통 템플릿·트리거 변경은 성진님 구현을 재사용해요.

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
- 오전의 Google 26개·Kubernetes SA 11개 검사는 운영자 impersonation/SA 회귀 결과예요. 오후에는 #45·#48을 반영한 네 리소스로 27개·12개를 재검증했어요. EKS 실제 경로 결과는 위 담당자 인계와 구분해요. [최신 연결 검증](gcp-integration-verification-2026-10-10.md)을 참고해요.
- #45·#48·#38·#49·#50·#51은 main에 반영됐어요. 실제 Application 적용·앱 배포·알림/baseline 검증은 다음 작업이에요.

## 카나리 오류 조치와 현재 조건

[PR #39](https://github.com/Crystal-SBHackathon2026/gitops/pull/39)의 공통 `error-rate` 지표는 GKE에 없는 Prometheus DNS를 참조해요. 2026-10-09 20:21–20:22 KST에 GKE Rollouts v1.10.0으로 이 지표만 시험해 `count=6`, `consecutiveErrorLimit=6`에서도 7회 연속 DNS 오류 후 AnalysisRun `Error`를 확인했어요. 시험 리소스는 삭제했어요.

이후 #42가 공통 오류를 해소했고 #45가 AWS Prometheus 분석과 로컬·GCP 응답 분석을 분리했어요. #48의 GCP 데모는 두 Service 블루그린이고 전환 전후 Analysis는 없어요. 이번 첫 연결에 Prometheus를 설치하지 않으며, AnalysisTemplate 존재나 최초 배포만으로 후속 분석·블루그린 전환 성공을 판정하지 않아요. [검증 기록](gcp-gke-verification-2026-10-09.md)에 과거 실패를 보존했어요.

## 검증 기준

- EKS 실제 실행 경로에서 TCP 443·CA/호스트 검증·GCP API 인증이 성공해요.
- `tokyo-gke`가 위 GKE를 가리키고 관리 범위가 `sample-app`에 제한돼요. 인증 만료·갱신과 장애 복구 조건을 기록해요.
- 실제 GKE Rollout·Pod Ready·내부 `/healthz`·`/api/info`와 `gcp/asia-northeast1`·이미지/앱 버전까지 확인해요. Synced만으로 완료하지 않아요.
- 중앙 GCP Notifications와 Review API 배포 기록을 확인해요. 외부 LB·후속 블루그린·GCP 검토/baseline·전체 환경 gate는 후속 완료 항목과 구분해요.
- 기존 AWS/local Application의 목적지·기존 AWS 알림·ESO Secret 공급에 예상하지 못한 변경이 없어요.

이 문서는 직접 보내지 않은 인계 요청문이에요. 이 채팅은 EKS 등록 Secret·Controller·IAM·네트워크를 수정하지 않아요.
