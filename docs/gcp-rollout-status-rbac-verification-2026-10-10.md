# 도쿄 GKE 수동 승격 권한 보완 검증 — 2026-10-10

중앙 Argo CD의 Google 배포 계정은 Rollout 본체를 수정할 수 있었지만 `rollouts/status` patch 권한이 없어 수동 Promote가 HTTP 403으로 실패했어요. GKE의 기존 `sample-app/argocd-deployer` Role에 status get/patch/update 규칙 하나를 추가하고 실제 API의 허용·거부와 server dry-run을 확인했어요. 실제 Promote는 성진님의 후속 검증 항목이에요.

- 작업: [gitops #37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)의 GCP namespace RBAC 후속 보완
- 요청: [성진님 21:00 Slack 기록](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791633648667899)
- 소스: [rbac.yaml](../argocd/install/gke/rbac.yaml), [검증 도구](../argocd/install/gke/Verify-GkeBootstrap.py), [운영 안내](../argocd/install/gke/README.md)
- 적용 시각: 2026-10-10 23:12 KST, 서비스 조회 시각: 23:17 KST

## 대상과 변경

| 항목 | 직접 확인한 값 |
| --- | --- |
| GCP 프로젝트 | `crystal-sbh2026-gcp-1009` |
| GKE | `tokyo-gke` / `asia-northeast1-a` |
| API | `https://34.146.143.116` |
| kube-system UID | `c249c507-6262-4b06-be44-ab019fa3256a` |
| sample-app namespace UID | `a973059f-62e9-4146-8fe2-1a51b883d16d` |
| 기존 Kubernetes 배포 SA UID | `b00980c6-fde1-4178-9c27-22350d595c81` |
| Google 배포 계정 | `argocd-tokyo-deployer@crystal-sbh2026-gcp-1009.iam.gserviceaccount.com` |

추가한 Role 규칙은 아래 한 개예요.

```yaml
- apiGroups: [argoproj.io]
  resources: [rollouts/status]
  verbs: [get, patch, update]
```

실환경에는 Role의 UID·resourceVersion·기존 규칙을 JSON Patch의 test 조건으로 확인한 뒤 위 규칙만 추가했어요. server dry-run 후 실제 적용·재조회를 통과했고 기존 Role UID를 유지했어요. Kubernetes SA와 두 RoleBinding, Google IAM/WIF, EKS 등록·Controller, Application, 앱 overlay는 변경하지 않았어요. 기존 namespace 조회 권한은 해당 namespace의 Secret 읽기도 포함하며, 이번 변경으로 Secret 쓰기나 다른 namespace·클러스터 권한을 추가하지 않았어요.

검증 도구는 두 인증 모드에서 status get/patch/update 허용과 다른 namespace의 Rollout status·Deployment status patch 거부를 확인해요. 기존 Rollout이 있을 때 `--verify-rollout-status`를 지정하면 status GET과 빈 merge patch의 `dryRun=All`도 실행해요. 토큰·API 응답 본문은 결과 파일에 기록하지 않아요.

## 실제 검증 결과

| 시각 KST | 인증 또는 검사 방법 | 결과와 한계 |
| --- | --- | --- |
| 21:12, 변경 전 | EKS argocd-server의 기존 공식 `argocd-k8s-auth gcp` + 등록된 ADC 설정 | 실제 WIF Google 계정 식별·권한 검사 등 11개 통과. status get 허용, patch/update 거부와 실제 status dry-run PATCH HTTP 403을 재현했어요. |
| 변경 전 | 보완한 검증 도구의 기존 Kubernetes SA 인증 | status patch 허용 검사에서 실패해 누락 권한을 검출했어요. |
| 23:12, 변경 후 | 기존 Kubernetes SA TokenRequest 인증 | 19개 통과. status 권한 5개, 실제 status GET·dry-run PATCH, 두 Service·Rollout·AnalysisTemplate 생성 dry-run을 포함해요. Rollouts v1.10.0 Ready·CRD 5개 Established도 확인했어요. |
| 23:15, 변경 후 | GKE 운영자의 Kubernetes User impersonation으로 Google 계정 이메일 지정 | 허용·거부 8개와 기존 Rollout status server dry-run PATCH 통과. Google WIF 토큰을 새로 교환한 검사는 아니에요. |
| 변경 후 | EKS argocd-server에서 공식 인증 재실행 시도 | 현재 PC에서 EKS API 접속이 타임아웃되어 WIF 재교환 이후 검증은 완료하지 못했어요. GKE의 RBAC 통과 결과와 구분해요. |

Google User impersonation 검사에서는 `sample-app`의 status get/patch/update만 허용되고, `kube-system`의 Rollout status patch·Deployment status patch·Secret patch·RoleBinding patch·노드 조회는 거부됨을 확인했어요. 실제 UI Promote·pause 해제·active Service 전환은 실행하지 않았어요. abort/pause/restart 등의 다른 UI 동작도 이번 검증 결과에 포함하지 않아요.

Python AST·YAML 구조·Role 규칙 한 개 추가·기존 SA/RoleBinding 보존·AWS/local/GCP 및 GKE bootstrap Kustomize 렌더링·문서 링크 13개·`git diff --check`도 통과했어요. 앱 쓰기 검사는 server dry-run이며 앱 테스트 리소스를 생성하지 않아요.

## 작업 PC의 GKE 접근 복구

작업 중 PC egress가 바뀌어 GKE 직접 조회가 타임아웃됐어요. 두 독립 HTTPS 서비스에서 `175.215.251.53`으로 실측하고 `175.215.251.53/32`만 GKE API 허용 목록에 추가했어요. 이전 PC 주소와 EKS egress를 모두 유지했어요.

```text
118.235.80.213/32
118.235.82.91/32
121.144.51.133/32
175.215.251.53/32
43.200.199.19/32
58.231.208.183/32
```

GKE authorized networks는 활성, 전체 Google 외부 CIDR 허용은 비활성이에요. `UPDATE_CLUSTER` 작업 `operation-1791641451401-65fe489e-d44e-440f-92ac-22ff53dac95e`는 23:10 KST에 DONE·오류 없음으로 끝났고 실제 허용 목록·API 접근을 재확인했어요. 최초 비동기 요청 후 CLI의 빈 JSON 배열을 처리하다 로컬 기록 오류가 났지만, 변경을 반복하지 않고 작업 상태를 조회해 성공을 확인한 뒤 결과 처리를 보완했어요.

현재 PC → EKS API 접근은 별도 타임아웃 상태예요. 이 채팅에서 EKS 허용 목록을 변경하지 않았으며 EKS 담당의 접근 확인이 필요해요. GKE 접근 복구 성공을 EKS 접근 복구나 WIF 사후 검증 성공으로 취급하지 않아요.

## 23:17 KST 서비스 조회

- Rollout UID는 `b4e5b4da-ed23-4ff5-afe1-f24d9ca0194e`이고 `Paused` / `BlueGreenPause`예요. `autoPromotionEnabled: false`를 유지해요.
- active는 `55d66b8fff`, preview는 `7d96d9d96c`를 가리키고 두 Service 모두 ClusterIP예요.
- 실제 Pod 4개가 모두 Ready예요. active 2개는 이미지 `8d9cfa260b3860835cb3a7c086903d6ad508a61f`, preview 2개는 `fc9fe8f13da60d5a9c27d72bb8c85a3c160a171c`예요.
- GKE API Service proxy로 두 Service의 `/healthz` 정상 응답과 `/api/info`의 `environment=gcp`, `region=asia-northeast1`, 각 이미지 태그와 일치하는 버전을 확인했어요. 공개 외부 접속 검증은 아니에요.
- 작업 중 팀 CI의 이미지 갱신으로 preview가 변경됐어요. 위 버전·selector는 조회 시점의 기록이며 최신 main 버전 또는 실제 Promote 이후 상태를 대신하지 않아요.

## 후속 확인

- 성진님이 중앙 Argo CD의 실제 Google 인증으로 Promote를 실행하고 새 active selector·Pod Ready·서비스 버전·Healthy 전환을 확인해요. 데모 시작 전에 최신 main의 v1 기준을 맞춰요.
- EKS 담당이 현재 PC의 API 접근을 확인한 뒤 공식 WIF 재교환 또는 실제 앱 동작 중 인증 갱신 결과를 확인해요.
- 도쿄 active Service의 외부 주소는 별도 작업이에요. 혜연님의 22:08 답장에서는 HTTP와 5050 서버 프록시 방식을 허용했어요. 23:14 시나리오 v2에서는 다중 환경 PR #64·#67을 내일 데모에 반영하지 않기로 했어요. 현재 main에서 공개 경로가 유지되는 방식·비용 승인을 확인한 뒤 연결해요.
- GCP 알림·검토 기록·baseline과 외부 주소에서 승격 전후 버전 전환은 별도 실제 검증 항목으로 남아요. 이번에는 새로운 LB·DB·노드·클러스터를 생성하지 않았어요.
