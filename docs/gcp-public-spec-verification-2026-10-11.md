# GCP 공개 Service 명세 전환 검증 — 2026-10-11

[이슈 #70](https://github.com/Crystal-SBHackathon2026/gitops/issues/70)의 문서 검증 기록이에요. 기존 PR #67 렌더러와 삭제 보호를 재사용해 현재 도쿄 공개 overlay와의 호환성을 확인했어요. 입력·출력·메모리 Git 검사와 실제 GKE 배포 결과를 구분해요. 적용 순서는 [공개 접속 운영 안내](gcp-public-service.md#명세-기반-배포를-활성화하는-순서)를 따라요.

## 기준과 소스

계약 검사 기준은 2026-10-11 02:08 KST예요. 원격 소스를 SHA로 고정해 분석 전용 디렉터리에서 실행했어요. 공유 checkout과 운영 파이프라인을 변경하지 않았어요.

| 소스 | 기준 SHA·파일 |
| --- | --- |
| gitops main | `c180dcdeca474bab4c71ca33fe205ad44743b159` — [GCP overlay](https://github.com/Crystal-SBHackathon2026/gitops/tree/c180dcdeca474bab4c71ca33fe205ad44743b159/apps/sample-app/overlays/gcp), [공통 base](https://github.com/Crystal-SBHackathon2026/gitops/tree/c180dcdeca474bab4c71ca33fe205ad44743b159/apps/sample-app/base) |
| review-service PR #67 | `543b6247ae3d9aedee550fb1ac0a640b63b168b7` — [명세 모델](https://github.com/Crystal-SBHackathon2026/review-service/blob/543b6247ae3d9aedee550fb1ac0a640b63b168b7/ai/review_ai/spec/deploy_spec.py), [렌더러](https://github.com/Crystal-SBHackathon2026/review-service/tree/543b6247ae3d9aedee550fb1ac0a640b63b168b7/ai/review_ai/overlay), [guard/commit](https://github.com/Crystal-SBHackathon2026/review-service/blob/543b6247ae3d9aedee550fb1ac0a640b63b168b7/worker/review_worker/commit_overlay.py) |
| sample-app main | `0e402802ea345ed5503a5f298f40fb49f887ae54` — 분석 입력과 기존 배포의 이미지 태그 |
| sample-app PR #38 공개 예제 | `353c6afd8fba93ae6a6ac32208d49f133e70fe76` — [deploy/gcp.yaml](https://github.com/Crystal-SBHackathon2026/sample-app/blob/353c6afd8fba93ae6a6ac32208d49f133e70fe76/examples/multi-target/deploy/gcp.yaml) |
| gitops PR #56 등록 안내 | `2bc81497eddaf27fac5c4a42a5f90e90a47daf26` — [등록 목록](https://github.com/Crystal-SBHackathon2026/gitops/blob/2bc81497eddaf27fac5c4a42a5f90e90a47daf26/examples/multi-target/registered-targets.json) |

PR #67의 [원 테스트](https://github.com/Crystal-SBHackathon2026/review-service/blob/543b6247ae3d9aedee550fb1ac0a640b63b168b7/ai/tests/test_overlay.py)를 Python 3.13 분석 환경에서 실행했어요. 해당 SHA의 `ai/`에서 아래 선택 테스트만 실행했고 **6 passed, 22 deselected**였어요.

```powershell
python -m pytest tests/test_overlay.py -k public_service -q
```

`pytest-asyncio` 미설치로 인한 `asyncio_mode` 설정 경고와 sandbox의 pytest cache 쓰기 경고 2개가 있었어요. 선택한 6개는 통과했지만 전체 AI/API/worker 테스트를 통과했다고 표시하지 않아요. 첫 별도 계약 검사 실행은 결과가 반환되지 않아 중단했어요. 원인은 확정하지 않았고 subprocess timeout을 추가한 재실행에서 아래 18개가 통과했어요.

## 현재 base와의 계약 검사 — 18/18

분석용 입력은 GCP `sample-app`, namespace `sample-app`, 포트 8080, replicas 2, 현재 이미지 태그, `DEPLOY_ENV=gcp`·`DEPLOY_REGION=asia-northeast1`, 공개 active Service·수동 bluegreen으로 구성했어요. 팀의 실제 로컬 PR A 파일은 아니에요.

현재 base에 기존 렌더러 출력을 연결해 `kubectl kustomize`로 두 출력을 비교했어요. 모델·렌더러·`make_overlay_guard`·`make_commit_overlay`는 PR #67의 실제 함수를 사용했고 Git 읽기/쓰기는 메모리 대역으로 처리했어요. 이 검사는 클러스터 API 호출이나 실제 원격 Git 커밋을 하지 않았어요.

| 검사 | 결과 |
| --- | --- |
| 1. 기존 AppSpec 모델이 입력 수용 | 통과 |
| 2. 렌더러의 차단 warning 없음 | 통과 |
| 3. `service-public.yaml` 의미상 YAML이 현재 공개 패치와 일치 | 통과 |
| 4. 출력 리소스의 kind/name 집합 유지 | 통과 |
| 5. active Service 전체 렌더링 출력 일치 | 통과 |
| 6. preview Service 전체 렌더링 출력 일치 | 통과 |
| 7. active가 LoadBalancer | 통과 |
| 8. preview가 내부 ClusterIP | 통과 |
| 9. active 기본 selector `app: sample-app` 유지 | 통과 |
| 10. 공개 패치가 selector·ClusterIP를 고정하지 않음 | 통과 |
| 11. bluegreen 전략 전체 일치 — active/preview·수동 승격·scaleDownDelaySeconds 30 | 통과 |
| 12. runtime 환경 값이 GCP | 통과 |
| 13. 기존 guard가 공개 계약 유지 허용 | 통과 |
| 14. 메모리 commit 출력에 공개 패치 포함 | 통과 |
| 15. 기존 guard가 공개 계약 제거 차단 | `OVERLAY_RESOURCE_REMOVED: service-public.yaml` |
| 16. 기존 commit이 공개 계약 제거 차단 | 통과 |
| 17. 차단된 공개 제거 요청의 쓰기 없음 | 통과 |
| 18. AWS에서 같은 공개 Service 명세 거절 | 통과 |

현재 base 대비 전체 Rollout의 차이는 `/spec/template/spec/terminationGracePeriodSeconds`에 `30`이 추가되는 것이었어요. PR #67 모델의 `runtime.termination_grace_seconds` 기본값이에요. Service·전략은 같아도 Pod template 선언이 달라지므로 실제 재생성 뒤 새 preview·Pod 교체 여부를 확인해야 해요. 이 검사는 API의 Service UID·할당 IP·동적 Rollouts selector 보존을 증명하지 않아요.

다른 입력으로 재검증할 때는 전체 모델 검증, 현재 base를 사용한 렌더링·전체 diff, 공개 계약 유지/제거의 guard와 commit 결과를 함께 확인해요. 현재 main과 실행 이미지가 바뀌면 이 SHA의 결과를 그대로 적용하지 않아요.

## 공개 예제와 실제 PR A 준비물을 구분해요

| 항목 | PR #38 공개 예제 | 분석 입력·현재 도쿄 | 연재님 로컬 PR A |
| --- | --- | --- | --- |
| 공개 Service 명세 | `network.service` 없음 | `LoadBalancer/public: true` | 준비 문서상 있음; 최종 파일 미검증 |
| 승격 | 자동·30초 | 수동 `auto_promotion: false` | 준비 문서상 수동; 최종 파일 미검증 |
| replicas | 3 | 2 | 최종 파일 미검증 |
| 목적 | 공개된 다중 환경 예제 | 현재 base 호환성 분석·기존 도쿄 운영 | 별도 통합 다중 환경 리허설 |

PR #38 예제는 PR #67 모델에서 유효하지만 기존 공개 파일이 출력되지 않아요. 기존 guard와 메모리 commit 모두 공개 파일 삭제로 차단하며 commit SHA·쓰기가 발생하지 않았어요. 이 예제를 현재 공개 경로의 입력으로 그대로 복사하면 안 돼요. PR #56의 자동 승격 30초 안내도 현재 수동 승격 계약과 대조해야 해요.

[연재님 준비 기록](https://github.com/Crystal-SBHackathon2026/review-service/blob/543b6247ae3d9aedee550fb1ac0a640b63b168b7/docs/slack-demo-followups.md)의 로컬 `demo/pr-a-main`은 공개 예제와 별도예요. 연재님·성진님이 실제 리허설에 사용할 최종 `deploy/gcp.yaml`을 확인한 뒤, GCP 담당이 위 검사를 그 파일로 다시 수행해요. 시점은 새 스키마/renderer 배포와 기능 활성화 전이에요. 현재 AWS 단일 명세 데모와 다중 환경 입력/CI 모드를 먼저 구분해요.

## 직접 실제 검증과 팀원 공유 결과

- **직접 확인 — 01:10 KST:** PR #68 main `c180dcd`가 중앙 Application의 두 source에 동기화됐고 대상은 `tokyo-gke/sample-app`이었어요. GKE kube-system UID가 [target.json](../argocd/install/gke/target.json)과 일치했어요. Pod 2개 Ready·Rollout Healthy·수동 승격 상태를 확인했어요.
- **직접 확인 — 같은 시각:** `http://34.85.123.113`의 `/healthz`·`/api/info` HTTP 200, `gcp/asia-northeast1`, 이미지/응답 버전 `0e402802ea345ed5503a5f298f40fb49f887ae54`였어요. active UID `fb466af7-ebeb-483f-8479-d2081a12f515`·ClusterIP `10.62.3.1`·selector hash `6d7f7645d7`를 유지했고 preview는 내부였어요. forwarding rule 1개·target pool HEALTHY·Service/health check 방화벽과 별도 예약 IP 없음도 확인했어요.
- **팀원 공유 — 01:48 KST:** 성진님이 [외부 응답 20/20 HTTP 200·세 환경 버전 일치](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791650901911239)를 재확인했어요. 이 문서의 직접 GCP 조회와 구분해요.
- **팀 합의 — 01:47 KST:** 성진님은 [Service를 overlay 밖으로 옮기는 제안을 철회](https://softbankhackathon2026.slack.com/archives/C0C1V166M5L/p1791650828387119)하고 PR #67 재사용·명세 준비 뒤 활성화·Service/selector 검증에 동의했어요. 별도 Service Application이나 세 번째 source를 추가하지 않아요.
- **최신 저장소 반영 — 02:35 KST:** 성진님의 [PR #71](https://github.com/Crystal-SBHackathon2026/gitops/pull/71)이 main `854fd090b4789908bb67503b95b67b41d8fb4422`로 머지됐어요. 중앙 Prometheus의 Endpoints가 도쿄 공개 IP를 참조하므로 IP 변경·LB 회수 때 모니터링/5050 담당과 함께 갱신·정리하는 조건을 운영 안내에 추가했어요. 타깃 up·env 라벨 aws/gcp·재시작 0회는 해당 PR의 팀원 검증 결과예요. 이 채팅에서 EKS 설정을 변경하거나 실제 지표 수집을 재검증하지 않았어요.

01:10 실제 검증은 PR #68의 기존 수동 overlay를 적용한 결과예요. PR #67의 새 렌더러가 운영에서 재생성한 결과가 아니에요. 현재 active와 preview가 같은 버전이므로 새 preview의 승격 전후 전환도 이 결과에 포함하지 않아요.

## 후속 담당과 완료 기준

| 항목 | 담당·조건 |
| --- | --- |
| 실제 PR A 파일·최종 계약 | 연재님·성진님과 파일/리허설 모드 확정, GCP 담당이 새 입력으로 전체 diff·삭제 보호 재확인 |
| 새 코드·실행 버전·DB 호환성 | 연재님·혜연님이 선행 PR/main·API/모든 worker 이미지·migration/인덱스 확인, NET-001 지식 동기화 확인 |
| 등록 목록·CI·활성화 | API/worker 동일 등록 목록과 성진님 CI variable/이미지 쓰기 경로를 합의; 상세 순서는 운영 안내 |
| 새 렌더러의 실제 GKE 반영 | 대상 UID·Service UID/ClusterIP/IP/selector·Pod/응답 버전·preview 내부·수동 승격 유지 확인 |
| PR A와 수동 승격 | 성진님과 새 preview Paused·승격 전 공개 URL의 이전 버전·Promote 뒤 같은 URL의 새 버전·후속 CI 확인 |
| 5050 화면 | 혜연님 서버 프록시의 도쿄 카드·환경/버전·자동 새로고침 확인 |
| 공개 IP 변경·운영 종료 | 성진님·EKS 담당의 중앙 모니터링 Endpoints/수집 연결, 혜연님의 5050 프록시를 함께 갱신/정리; GCP 담당은 새 주소·서비스 응답 또는 LB 회수를 확인 |
| 알림·baseline·WIF 갱신 | 성진님·혜연님·연재님과 실제 수신/기록 연결; GCP 담당은 앱 트래픽 중 인증 갱신 결과 확인 |
| EKS 기반 변경 | 이 채팅에서 수정하지 않고 EKS 담당에 이유·대상·검증 기준을 요청 |

이번 문서 검증에서는 실제 팀 PR A 입력 검증, 원격 Git 커밋, 기능 플래그/CI 활성화, 클러스터 apply/server dry-run, Promote, 5050 화면 확인을 실행하지 않았어요. 문서 변경은 링크·명세 예제/기존 모델·PowerShell 구문·변경 범위·`git diff --check`로 정적 검증해요.

02:29 KST 문서 검사에서 로컬 링크/앵커 16개, YAML 예제 1개의 기존 모델 수용·현재 공개 패치 일치·namespace/포트/수동 승격 조건, PowerShell 예제 4개의 구문 검사를 통과했어요. 명령 예제는 실행하지 않았어요. 변경은 README와 이 문서를 포함한 docs 2개이며 `apps/`·`argocd/`·`scripts/`의 차이 없음과 diff/공백 검사도 통과했어요.

02:37 KST에 최신 main `854fd09`를 통합한 뒤 로컬 링크/앵커 17개·기존 YAML/모델 조건·문서 변경 범위를 다시 통과했어요. PR #71의 Endpoints IP/포트·ServiceMonitor 경로/간격을 main YAML과 대조했고 `monitoring/`·`argocd/` 변경을 보존했어요. 기존 계약 검사 기준 `c180dcd`와 최신 main 사이의 sample-app base/overlay·GCP Application·GKE 연결 파일에는 차이가 없었어요.

문서 작업 #70과 실제 공동 검증 [#66](https://github.com/Crystal-SBHackathon2026/gitops/issues/66)·[#37](https://github.com/Crystal-SBHackathon2026/gitops/issues/37)을 분리해 관리해요. 전체 연결 투두와 팀원용 연결 예시는 [팀 Notion](https://app.notion.com/p/3f48bee9ada481e2bec4f8940a6cd4a4)에 이어서 기록해요. 운영 종료·수동 회수는 기존 운영 안내를 따르며 자동 삭제를 추가하지 않아요.
