# Argo CD · Argo Rollouts 설치 기록

클러스터에 배포 도구를 설치하는 순서와 버전을 남깁니다. 어느 환경에서든 같은 순서로 설치하면 됩니다.
Terraform이 관리하는 AWS 리소스(VPC, ALB, RDS 등)와는 소유 범위가 다릅니다. 여기 있는 것은 **클러스터 안에서 도는 배포 도구**만입니다.

| 도구 | 버전 | namespace | 역할 |
| --- | --- | --- | --- |
| Argo CD | v3.5.4 | `argocd` | gitops 레포를 보고 클러스터에 배포 |
| Argo Rollouts | v1.10.0 | `argo-rollouts` | `Rollout` 리소스 처리, 헬스체크 실패 시 자동 롤백 |

- Argo CD는 **배포 대상 클러스터 안에 설치**합니다(in-cluster). 별도 IAM 역할이나 EKS access entry가 필요하지 않습니다.
- UI용 로드밸런서는 만들지 않습니다. 필요할 때만 `kubectl port-forward`로 접속합니다.
- sample-app은 `Rollout`으로 배포되므로 Argo Rollouts를 먼저 설치해야 합니다. 없으면 `no matches for kind "Rollout"` 오류가 납니다.

### 환경별 운영 모델 (2026-10-09 합의)

| 환경 | Argo CD 위치 | Application 목적지 | 상태 |
| --- | --- | --- | --- |
| AWS EKS | EKS 안 | `server: kubernetes.default.svc` (자기 자신) | 돌아감 |
| 로컬 k3s | **로컬 클러스터 안** (pull) | `name: crystal-busan` | 돌아감 |
| GCP GKE | 중앙 EKS | `name: tokyo-gke` | GKE 없음 |

로컬은 중앙 EKS 에서 들여다보지 않고 **스스로 이 레포를 읽습니다**. 데모 중에 Tailscale 같은 인바운드 경로를 유지하지 않아도 되는 쪽을 택했습니다.

🔴 **local·gcp Application 은 `server` 가 아니라 `name` 을 씁니다.** `kubernetes.default.svc` 는 "Argo CD 가 있는 클러스터" 라서, local 파일을 EKS 에 적용하면 local overlay 가 EKS 에 배포되어 aws overlay 를 밀어냅니다(네임스페이스가 둘 다 `sample-app`). 10/9 에 실제로 그 상태였습니다. 이름을 쓰면 등록 안 된 클러스터에서 `cluster not found` 로 **명확히 실패**합니다.

## 설치

```bash
# 1. Argo CD
kubectl create namespace argocd
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.4/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s

# 2. Argo Rollouts
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts --server-side -f https://github.com/argoproj/argo-rollouts/releases/download/v1.10.0/install.yaml
kubectl -n argo-rollouts rollout status deploy/argo-rollouts --timeout=300s

# 3. Application 연결 (그 클러스터에 맞는 파일만)
kubectl apply -f argocd/sample-app-aws.yaml      # EKS 의 Argo CD 에서만
kubectl apply -f argocd/sample-app-local.yaml    # 로컬 k3s 의 Argo CD 에서만 (아래 등록 먼저)
# argocd/sample-app-gcp.yaml                     # GKE 등록 뒤
```

## 로컬(부산) k3s 환경

k3d 로 띄운 `crystal-busan` 클러스터입니다. 위 설치 순서를 그대로 쓰고, Application 적용 전에 **클러스터를 이름으로 등록**합니다.

```bash
k3d cluster create crystal-busan --agents 1 -p "8081:80@loadbalancer"
# 이미 만들어 뒀으면: k3d cluster start crystal-busan   (Docker Desktop 이 떠 있어야 한다)
```

```bash
# 로컬 Argo CD 에 자기 클러스터를 crystal-busan 이라는 이름으로 등록한다.
# 이 이름은 로컬에만 있으므로 같은 파일을 EKS 에 적용하면 cluster not found 로 실패한다.
kubectl apply -f - <<'YAML'
apiVersion: v1
kind: Secret
metadata:
  name: cluster-crystal-busan
  namespace: argocd
  labels:
    argocd.argoproj.io/secret-type: cluster
stringData:
  name: crystal-busan
  server: https://kubernetes.default.svc
  config: '{"tlsClientConfig":{"insecure":false}}'
YAML

kubectl apply -f argocd/sample-app-local.yaml
```

확인:

```bash
kubectl -n argocd get application sample-app-local
curl http://localhost:8081/api/info
# {"app":"sample-app","version":"<커밋 SHA>","environment":"local","region":"busan-local", ...}
```

- **Docker Desktop 이 꺼져 있던 동안 폴링이 멈춥니다.** 다시 켜면 리비전이 며칠 전에 머물러 있으면서 `Synced` 로 보입니다. 폴링 주기를 기다리거나 강제로 다시 읽힙니다.
  ```bash
  kubectl -n argocd annotate application sample-app-local argocd.argoproj.io/refresh=hard --overwrite
  ```
- 로컬은 `argocd-cm` 재조회 주기를 줄이지 않았습니다(기본 180초). 데모에서 빠르게 보여줘야 하면 EKS 와 같이 30초로 줄입니다 — 위 "git 을 다시 읽는 주기" 절 참고.
- `-p "8081:80@loadbalancer"` 는 모든 인터페이스에 열립니다. 같은 LAN 에서 접속됩니다. 다른 기기로 시연할 때는 편하고, 막으려면 `127.0.0.1:8081:80` 으로 클러스터를 다시 만들어야 합니다.
- Notifications 는 아직 안 붙였습니다. 로컬 Argo CD 가 Review API 에 닿으려면 **공개 주소**(플랫폼 ALB 의 `/webhooks/argocd`)와 토큰 공급이 필요합니다 — 박찬건님 작업.

## 확인

```bash
kubectl -n argocd get application sample-app-aws
kubectl -n sample-app get rollout,pods,svc,ingress
```

`Synced` / `Healthy`가 되면 Ingress의 ADDRESS(ALB 주소)로 접속해 응답 환경을 확인합니다.

```bash
curl http://<ALB 주소>/api/info
# {"app":"sample-app", ... ,"environment":"aws","region":"ap-northeast-2"}
```

## Argo CD UI 접속

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
# https://localhost:8080 — 사용자 admin
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
```

초기 비밀번호는 로그인 후 바꾸고, 바꾼 뒤에는 `argocd-initial-admin-secret`을 삭제합니다. 비밀번호는 git·Slack·문서에 남기지 않습니다.

## git 을 다시 읽는 주기

기본 180초다. gitops 에 Argo CD 웹훅을 걸 수 없어서(`argocd-server` 가 ClusterIP, Ingress 없음) 폴링이 유일한 경로다. 실측하니 커밋에서 배포까지 71초~3분 걸려 30초로 줄였다.

```bash
kubectl -n argocd patch cm argocd-cm --type merge   --patch-file argocd/install/reconciliation-timeout.patch.yaml
kubectl -n argocd rollout restart statefulset/argocd-application-controller
```

`argocd-cm` 에는 설치가 넣은 키가 9개 더 있다. **`apply` 로 쓰면 그것들이 지워지므로 반드시 `patch` 를 쓴다.** 설정은 컨트롤러를 재시작해야 읽는다.

**`jitter` 를 0 으로 두지 않으면 주기가 30초가 아니다.** Argo CD 는 재조회 주기에 0~jitter 사이의 무작위 시간을 더하고 기본값이 1분이다. `timeout.reconciliation` 만 바꾸면 실제 주기가 30~90초가 된다(실측 87초). 시작 로그로 확인할 수 있다.

```bash
kubectl -n argocd logs argocd-application-controller-0 | grep appResyncPeriod
# appResyncPeriod=30s, appHardResyncPeriod=0s, appResyncJitter=0s
```

## 배포 결과를 검토 서비스로 보내기

`argocd/notifications/` 를 참고한다. 배포 성공·실패를 Review API 로 보내 업무 DB 에 baseline 을 쌓는다. 토큰은 `argocd` 전용 ESO 컨트롤러가 Secrets Manager 에서 넣는다 — 손으로 넣지 않는다.

## AWS(EKS) 환경에서 주의할 점

- EKS API는 허용된 IP에서만 접속됩니다. 설치 명령을 실행할 PC의 IP가 allowlist에 있어야 합니다.
- 설치 후 배포는 Argo CD가 클러스터 안에서 처리하므로, 사람이 kubectl로 접속할 일은 줄어듭니다.
- AWS Load Balancer Controller와 External Secrets Operator는 인프라(Terraform) 쪽에서 이미 설치·관리합니다. 여기서 다시 설치하지 않습니다.
