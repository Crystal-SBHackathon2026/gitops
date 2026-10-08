# gitops

Argo CD가 바라보는 배포 설정 레포입니다. CI가 이미지 태그를 갱신하면 Argo CD가 각 클러스터에 자동으로 동기화합니다.

```
apps/sample-app/
  base/                 공통 Rollout(Argo Rollouts), Service (이미지 태그는 CI가 갱신)
  overlays/local/       부산 로컬 (k3s)
  overlays/aws/         서울 (EKS, ap-northeast-2)
  overlays/gcp/         도쿄 (GKE, asia-northeast1)
apps/review-service/    검토 서비스(Review API·워커). AWS EKS platform 네임스페이스 전용
argocd/                 클러스터별 Argo CD Application
  install/              Argo CD · Argo Rollouts 설치 순서와 버전
```

렌더링 확인: `kubectl kustomize apps/sample-app/overlays/aws`

설치 순서와 버전은 [argocd/install/README.md](argocd/install/README.md)를 따릅니다.

## 로컬(부산) 환경 실행
```bash
k3d cluster create crystal-busan --agents 1 -p "8081:80@loadbalancer"
kubectl create namespace argocd
kubectl apply -n argocd --server-side -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl create namespace argo-rollouts
kubectl apply -n argo-rollouts --server-side -f https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml
kubectl apply -f argocd/sample-app-local.yaml
```
접속: http://localhost:8081 (Windows에서 kubectl 연결이 안 되면 `kubectl config set-cluster k3d-crystal-busan --server=https://127.0.0.1:<포트>`)

## 헬스체크 실패 시 자동 롤백
sample-app은 Argo Rollouts의 Rollout으로 배포됩니다. 새 버전이 60초(`progressDeadlineSeconds`) 안에 헬스체크(`/healthz`)를 통과하지 못하면 배포를 자동 중단하고 기존 버전을 계속 서비스합니다. 각 클러스터에 Argo Rollouts 설치가 필요합니다.
