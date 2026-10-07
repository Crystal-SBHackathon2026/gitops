# gitops

Argo CD가 바라보는 배포 설정 레포입니다. CI가 이미지 태그를 갱신하면 Argo CD가 각 클러스터에 자동으로 동기화합니다.

```
apps/sample-app/
  base/                 공통 Deployment, Service (이미지 태그는 CI가 갱신)
  overlays/local/       부산 로컬 (k3s)
  overlays/aws/         서울 (EKS, ap-northeast-2)
  overlays/gcp/         도쿄 (GKE, asia-northeast1)
argocd/                 클러스터별 Argo CD Application
```

렌더링 확인: `kubectl kustomize apps/sample-app/overlays/aws`
