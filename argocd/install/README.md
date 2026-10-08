# Argo CD · Argo Rollouts 설치 기록

클러스터에 배포 도구를 설치하는 순서와 버전을 남깁니다. 어느 환경에서든 같은 순서로 설치하면 됩니다.
Terraform이 관리하는 AWS 리소스(VPC, ALB, RDS 등)와는 소유 범위가 다릅니다. 여기 있는 것은 **클러스터 안에서 도는 배포 도구**만입니다.

| 도구 | 버전 | namespace | 역할 |
| --- | --- | --- | --- |
| Argo CD | v3.5.4 | `argocd` | gitops 레포를 보고 클러스터에 배포 |
| Argo Rollouts | v1.10.0 | `argo-rollouts` | `Rollout` 리소스 처리, 헬스체크 실패 시 자동 롤백 |

- Argo CD는 **배포 대상 클러스터 안에 설치**합니다(in-cluster). 그래서 Application의 목적지는 `https://kubernetes.default.svc`이고, 별도 IAM 역할이나 EKS access entry가 필요하지 않습니다.
- UI용 로드밸런서는 만들지 않습니다. 필요할 때만 `kubectl port-forward`로 접속합니다.
- sample-app은 `Rollout`으로 배포되므로 Argo Rollouts를 먼저 설치해야 합니다. 없으면 `no matches for kind "Rollout"` 오류가 납니다.

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

# 3. Application 연결 (환경에 맞는 파일 하나)
kubectl apply -f argocd/sample-app-aws.yaml      # AWS (EKS)
kubectl apply -f argocd/sample-app-local.yaml    # 로컬 (k3s)
kubectl apply -f argocd/sample-app-gcp.yaml      # GCP (GKE)
```

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

## AWS(EKS) 환경에서 주의할 점

- EKS API는 허용된 IP에서만 접속됩니다. 설치 명령을 실행할 PC의 IP가 allowlist에 있어야 합니다.
- 설치 후 배포는 Argo CD가 클러스터 안에서 처리하므로, 사람이 kubectl로 접속할 일은 줄어듭니다.
- AWS Load Balancer Controller와 External Secrets Operator는 인프라(Terraform) 쪽에서 이미 설치·관리합니다. 여기서 다시 설치하지 않습니다.
