# gitops

![전체 흐름에서 gitops 의 자리](docs/architecture.png)

> 위 그림 ③ 의 **"gitops 레포에 커밋"** 과 **Argo CD** 가 이 레포입니다. 검토를 통과한 명세와 CI 가 빌드한 이미지 태그가 여기로 모이고, Argo CD 가 각 환경에 배포합니다.
> 그림 원본은 [docs/architecture.excalidraw](docs/architecture.excalidraw) (Excalidraw).

Argo CD가 바라보는 배포 설정 레포입니다. 앱 레포의 CI가 이미지 태그를 갱신하면 Argo CD가 각 클러스터에 자동으로 동기화합니다. **사람이 이 레포를 직접 고치는 일은 거의 없습니다.**

```
apps/sample-app/
  base/                      공통 Rollout·Service·AnalysisTemplate (이미지 태그는 CI가 갱신)
  overlays/local/            부산 로컬 (k3s)
  overlays/aws/              서울 (EKS, ap-northeast-2)
  overlays/gcp/              도쿄 (GKE, asia-northeast1)
apps/review-service/         검토 서비스. AWS EKS platform 네임스페이스 전용
                             Review API · 워커 · Qdrant · 시크릿 · 플랫폼 ALB 연결
argocd/                      클러스터별 Argo CD Application
  install/                   Argo CD · Argo Rollouts 설치 순서와 버전, 재조회 주기
  notifications/             배포 결과를 검토 서비스로 보내는 설정
```

렌더링 확인: `kubectl kustomize apps/sample-app/overlays/aws`

## 누가 이 레포에 커밋하나

세 곳이 커밋합니다. 같은 시점에 겹칠 수 있어 **push 충돌 시 재시도**가 모두 들어가 있습니다.

| 누가 | 무엇을 |
| --- | --- |
| sample-app CI | `apps/sample-app/base` 의 이미지 태그 |
| review-service CI | `apps/review-service` 의 이미지 태그 |
| `commit_overlay` (검토 워커) | 검토를 통과한 명세로 만든 `overlays/<env>/` |

## 배포 방식

### 카나리 — 절반만 먼저 내보낸다

```
새 이미지 → 50% (복제본이 2개면 새 버전 1개 + 옛 버전 1개)
         → 60초 동안 /api/info 응답 확인 (10초마다 6번)
         → 멀쩡하면 100%, 계속 틀리면 중단하고 되돌림
```

단계는 `apps/sample-app/base/rollout.yaml`, 확인 기준은 `base/analysistemplate.yaml` 에 있습니다. 명세의 `rollout.strategy` 가 `canary` 면 이 설정을 그대로 쓰고, `bluegreen` 이면 렌더러가 전략을 통째로 바꿉니다.

Prometheus가 아직 없어서 `web` 프로바이더로 **앱 응답을 직접** 봅니다. 그래서 **일부 요청만 실패하는 부분 에러율은 잡지 못합니다**(이슈 #24). Prometheus가 올라오면 메트릭을 추가합니다.

### 헬스체크 실패 시 자동 롤백

새 버전이 60초(`progressDeadlineSeconds`) 안에 헬스체크(`/healthz`)를 통과하지 못하면 배포를 중단하고 기존 버전을 계속 서비스합니다. 카나리 분석과 별개로 동작하는 더 바깥의 안전장치입니다.

### 명세에 없는 리소스는 지워진다

`overlays/<env>/` 는 **생성물**입니다. `commit_overlay` 가 명세로 다시 만들면서, 이전에 있었는데 새 명세에 없는 파일은 지웁니다. 남겨두면 kustomize가 없는 리소스를 참조하기 때문입니다.

> ⚠️ 2026-10-09에 이것 때문에 장애가 있었습니다. 명세가 없는 PR에서 축소된 명세가 자동 생성·병합되어 `ingress.yaml` 이 지워지고, Argo CD prune → ALB까지 삭제됐습니다. 지금은 **기존 overlay의 Ingress가 사라지는 변경을 `commit_overlay` 가 `blocked` 로 막습니다.**

## 설치

버전과 순서는 [argocd/install/README.md](argocd/install/README.md)를 따릅니다. Argo CD **v3.5.4**, Argo Rollouts **v1.10.0** 으로 고정합니다. `stable`·`latest` 를 쓰면 환경마다 버전이 달라집니다.

배포 결과를 검토 서비스로 보내는 설정은 [argocd/notifications/README.md](argocd/notifications/README.md)에 있습니다.

## Application 목적지

| 파일 | `destination.server` | 상태 |
| --- | --- | --- |
| `sample-app-aws.yaml` | `https://kubernetes.default.svc` | 적용됨. Argo CD가 EKS 안에 있어 in-cluster가 맞습니다 |
| `review-service-aws.yaml` | `https://kubernetes.default.svc` | 적용됨 |
| `sample-app-local.yaml` | `LOCAL_K3S_API_SERVER` | **아직 적용하지 않습니다** |
| `sample-app-gcp.yaml` | `GCP_GKE_API_SERVER` | **아직 적용하지 않습니다** |

**운영 모델에 따라 `local`·`gcp` 의 값이 달라집니다.**

- **EKS의 Argo CD 하나로 세 환경을 관리**하면 → 클러스터를 Argo CD에 등록하고 그 주소(또는 `destination.name` 으로 등록한 이름)를 넣습니다
- **환경마다 Argo CD를 따로 설치**하면 → 그 클러스터 안에서는 `https://kubernetes.default.svc` 가 맞습니다

> ⚠️ 하나로 관리하면서 `local` 에 `kubernetes.default.svc` 를 넣으면 **로컬 설정이 EKS에 배포됩니다.** 네임스페이스가 둘 다 `sample-app` 이라 `aws` overlay와 같은 Rollout·Service·Ingress를 서로 밀어냅니다.

## 로컬(부산) 환경 실행

k3d 클러스터 안에 Argo CD를 따로 설치하는 방식입니다. 이 경우 Application의 목적지는 그 클러스터 자신입니다.

```bash
k3d cluster create crystal-busan --agents 1 -p "127.0.0.1:8081:80@loadbalancer"

kubectl create namespace argocd
kubectl apply -n argocd --server-side \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/install.yaml
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts --server-side \
  -f https://github.com/argoproj/argo-rollouts/releases/download/v1.10.0/install.yaml

# 목적지를 이 클러스터로 바꿔서 적용한다 (레포의 플레이스홀더는 그대로 둔다)
sed 's|LOCAL_K3S_API_SERVER|https://kubernetes.default.svc|' argocd/sample-app-local.yaml \
  | kubectl apply -f -
```

접속: http://localhost:8081

포트를 `127.0.0.1:` 로 묶은 이유는, 그냥 `8081:80` 으로 두면 모든 인터페이스에 열려 같은 네트워크의 다른 기기에서도 접속되기 때문입니다. 다른 기기로 시연할 계획이면 이 접두어를 빼야 합니다.

Windows에서 kubectl 연결이 안 되면: `kubectl config set-cluster k3d-crystal-busan --server=https://127.0.0.1:<포트>`

**카나리 분석이 로컬에서도 돌려면** 그 클러스터에 Argo Rollouts가 설치돼 있어야 합니다. `AnalysisTemplate` 은 `base` 에 있어 overlay를 쓰면 자동으로 따라갑니다.
