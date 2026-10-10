# 다중 환경 연결 예시 — 아직 적용하지 않음

현재 `apps/`, `argocd/`, review-service ConfigMap 및 이미지 태그는 변경하지 않았다.
이 예시는 클러스터가 실제로 준비됐다는 증거가 아니다. 특히 GCP Application의 준비 상태를 별도로 확인해야 한다.

`registered-targets.json`을 확인한 환경만 추려 API와 worker의 `DEPLOYMENT_TARGETS_JSON`에 동일하게 설정한다.
AWS의 `in-cluster`는 현재 Application의 `server: https://kubernetes.default.svc`를 뜻한다.
region은 선택한 명세와 등록 설정이 맞는지 확인하는 값이다. 새 클러스터를 만들거나 Argo destination을 자동 변경하지 않는다.

활성화 전에 배포 담당과 확인할 내용:

- API와 worker를 모두 새 코드로 업그레이드하되 `MULTI_TARGET_ENABLED=false`로 유지한다.
- sample-app CI 변경도 먼저 적용하고, repository variable `MULTI_TARGET_ENABLED=true`를 서비스 활성화와 맞춘다.
- 기존 단일 명세의 CI는 활성화 후 해당 환경 overlay에만 이미지 태그를 쓴다.
- 다중 환경 PR의 main CI는 이미지만 빌드·푸시한다. 부모 조정자가 CI 성공 후 이미지와 모든 선택 overlay를 한 GitOps 커밋으로 쓴다.
- 선택하지 않은 overlay는 최초 다중 배포 때 현재 이미지 버전으로 고정된다. YAML 표현·주석은 바뀔 수 있으나 렌더링된 리소스·버전은 유지한다.
- GCP의 직접 설정한 자동 승격 지연 `autoPromotionSeconds: 30`은 `rollout.auto_promotion_seconds: 30`으로 명세에 옮긴다. 수동 ingress/PVC는 명세로 옮기기 전 자동 삭제가 차단된다.
- 같은 Application에 수동 이미지 배포와 새 조정자를 동시에 운영하지 않는다. 검토 이후 선택 overlay/base가 바뀌면 새 배포가 차단되므로 다시 검토한다.

실제 적용 순서·API 계약·테스트는 review-service의 `docs/multi-target.md`를 따른다.
기능을 끄는 것만으로 이미지 pin이나 DB 인덱스가 이전 상태로 돌아가지는 않는다. 이전 이미지로 되돌리기 전에 진행 중 요청을 중단하고 pin 및 DB 호환성을 검토한다.
