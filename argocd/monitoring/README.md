# 모니터링 (Prometheus · Grafana)

배포가 멀쩡한지를 **숫자로** 판단하기 위해 둔다. 지금 카나리는 앱 응답을 직접 보는 방식이라, 응답은 오는데 **일부 요청만 실패하는 상황을 못 잡는다**. 그걸 잡는 게 이 묶음의 첫 목적이다 (이슈 #24).

## 누가 무엇을

2026-10-09 합의. 한 Prometheus 를 같이 쓰고 대시보드만 나눈다.

| 담당 | 범위 | Grafana 폴더 |
| --- | --- | --- |
| 이성진 | 앱 — `sample-app` `/metrics`, Argo CD · Rollouts 지표, 카나리 분석 | `apps/` |
| 김혜연 | 플랫폼 — Review API · 워커 지표, Kafka consumer lag, 커밋별 타임라인 | `platform/` |

### 🔴 라벨에 커밋 SHA 를 넣지 않는다

`app` · `env` 두 개만 쓴다. 커밋 SHA 를 라벨에 넣으면 **배포할 때마다 시계열이 통째로 새로 생겨** 메모리를 계속 먹는다 (김혜연 지적).

커밋 단위로 봐야 할 때는 두 경로가 있다.

- 업무 DB 타임라인 + Grafana 배포 어노테이션 (`deploy_events`) — 김혜연
- `kube_pod_container_info` 의 이미지 태그. 지금 이미지 태그가 곧 병합 SHA 라서, "지금 뜬 게 어느 커밋인지"는 시계열을 늘리지 않고 확인된다

## 설치

### 1. Grafana 관리자 Secret 을 먼저 만든다

**값은 git·슬랙·문서에 남기지 않는다.** 차트의 기본 비밀번호(`prom-operator`)를 쓰지 않으려고 `existingSecret` 으로 받는다.

```bash
kubectl create namespace monitoring

# 비밀번호를 만들어 바로 Secret 으로 넣는다 (화면에 찍지 않는다)
kubectl -n monitoring create secret generic grafana-admin \
  --from-literal=admin-user=admin \
  --from-literal=admin-password="$(python -c 'import secrets;print(secrets.token_urlsafe(24))')"
```

나중에 값을 확인할 때는 이렇게 본다.

```bash
kubectl -n monitoring get secret grafana-admin -o jsonpath='{.data.admin-password}' | base64 -d
```

> Secret 을 Argo CD 보다 먼저 만들어야 한다. 없으면 Grafana 파드가 `CreateContainerConfigError` 로 멈춘다.
> 예선 뒤에는 Secrets Manager + ESO 로 옮긴다 (`argocd/notifications/` 와 같은 방식).

### 2. Application 적용

```bash
kubectl apply -f argocd/monitoring-aws.yaml
kubectl -n argocd get application monitoring-aws -w
```

CRD 가 커서 `ServerSideApply=true` 를 켜 뒀다. 없으면 `metadata.annotations: Too long` 으로 실패한다.

## 확인

```bash
kubectl -n monitoring get pods
kubectl -n monitoring get pvc          # Bound 여야 한다

# 긁고 있는 대상
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
#   http://localhost:9090/targets

# Grafana
kubectl -n monitoring port-forward svc/monitoring-grafana 3000:80
#   http://localhost:3000  — 사용자 admin
```

## 정한 것과 이유

| 항목 | 값 | 왜 |
| --- | --- | --- |
| 차트 | `91.9.0` 고정 | `latest` 를 쓰면 환경마다 다른 게 올라간다. 최신(92.2.0)은 하루 전 릴리스라, 운영자 버전이 같으면서 묵은 쪽을 골랐다 |
| scrape | 30초 | 노드 t3.medium 3대 규모에 맞춘다 |
| 보존 | 2일 / 8GB | 김혜연 타임라인 대시보드가 며칠치를 볼지에 맞춰 조정한다 |
| 저장소 | `oneaction-monitoring-gp3` | 박찬건이 만든 gp3 `Retain` StorageClass. **EBS CSI 가 10/9 에 설치돼서** 쓸 수 있게 됐다 |
| Alertmanager | 끔 | 알림을 보낼 곳이 없다. 자리를 아낀다 |
| `kubeControllerManager`·`kubeScheduler`·`kubeEtcd`·`kubeProxy` | 끔 | EKS 는 관리형 컨트롤 플레인이라 긁을 수 없다. 켜 두면 계속 빨갛게 뜬다 |
| `*SelectorNilUsesHelmValues: false` | | 켜 두면 **이 차트가 만든 ServiceMonitor 만** 본다. 검토 서비스 등 다른 네임스페이스 것도 집어가게 끈다 |
| Grafana 로드밸런서 | 안 만듦 | Argo CD 와 같다. 필요할 때 `port-forward` |

## 긁는 대상

- 클러스터 기본 — kube-state-metrics, node-exporter, kubelet, API 서버
- **Argo CD** — `argocd` 네임스페이스의 metrics 서비스 4개 (동기화 상태, 앱 health)
- **Argo Rollouts** — 카나리 단계·분석 결과
- **`sample-app` `/metrics`** — 요청 수·지연·프로세스 지표 (sample-app [#21](https://github.com/Crystal-SBHackathon2026/sample-app/pull/21), 이슈 #32)
- 검토 서비스 — 김혜연이 ServiceMonitor 를 만들면 자동으로 붙는다

### sample-app ServiceMonitor 를 왜 여기 뒀나

둘 다 안 되는 자리가 있어서 모니터링 묶음이 직접 들고 있는다.

| 자리 | 왜 안 되나 |
| --- | --- |
| `apps/sample-app/overlays/aws/` | 렌더러가 다시 만드는 파일이라 지워진다. `APP_VERSION` 을 overlay env 로 뒀다가 같은 일을 겪었다 |
| `apps/sample-app/base/` | 로컬 k3s 에는 ServiceMonitor CRD 가 없다. base 에 두면 `sample-app-local` 이 동기화에 실패한다 |

모니터링은 AWS 에만 있으므로 이 자리가 맞다.

**함정 둘.**

- Service 자신에게 라벨이 있어야 한다. ServiceMonitor 의 `selector` 는 **파드 라벨이 아니라 Service 의 라벨**을 본다. `apps/sample-app/base/service.yaml` 에 `labels.app: sample-app` 을 넣었다. 없으면 아무것도 안 붙는데 **오류도 안 난다** (Argo Rollouts 서비스 이름을 `argo-rollouts-metrics` 가 아니라 `argo-rollouts` 로 썼을 때와 같은 종류의 실수다)
- `rollouts_pod_template_hash` 를 relabeling 으로 남긴다. 카나리 중에는 새 파드와 옛 파드가 같은 Service 뒤에 함께 있어서, 이 라벨이 없으면 지표가 섞이고 "새 버전만 에러가 난다" 를 볼 수 없다. **이슈 #24 가 이것 없이는 성립하지 않는다.** AnalysisTemplate 에서 `valueFrom.podTemplateHashValue: Latest` 로 받아 쓴다

붙었는지 확인:

```bash
kubectl -n monitoring port-forward svc/monitoring-kube-prometheus-prometheus 9090:9090
# http://localhost:9090/targets → serviceMonitor/monitoring/sample-app 가 up
```

```promql
# 에러율 — #24 가 쓸 식
sum(rate(http_requests_total{app="sample-app",env="aws",status=~"5.."}[1m]))
  / sum(rate(http_requests_total{app="sample-app",env="aws"}[1m]))
```
