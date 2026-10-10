# telemetry-collector — EKS 메트릭 → MSK `telemetry.metrics`

다중 클러스터 텔레메트리(본선 확장)의 1단계. **EKS 만.** GKE·로컬 k3s 는 아직 없다.

```
Prometheus (kube-prometheus-stack, 릴리스 monitoring)   ← 그대로. 설정·재시작 없음
   │  GET /federate (15초, match[] 로 필요한 것만)
   ▼
telemetry-collector (monitoring, Deployment 1개, otelcol-contrib 0.162.0)
   resource: cluster=aws-seoul, env=aws  →  batch
   ▼
MSK  topic telemetry.metrics   encoding otlp_json   key "aws-seoul"
```

## 기존 것과의 관계

- **kube-prometheus-stack·`argocd/monitoring-aws.yaml` 은 건드리지 않는다.** 서울 카나리 분석(AnalysisTemplate)이 그 Prometheus 를 본다.
  이 수집기는 그 Prometheus 의 `/federate` 를 Service(`monitoring-kube-prometheus-prometheus:9090`)로 읽기만 한다.
- 추가만 한다: `argocd/telemetry-collector-aws.yaml`, `monitoring/telemetry-collector/` (Deployment·ConfigMap). 지우면 원래대로.
- 토픽은 MSK `auto.create.topics.enable=true`(infra `msk/main.tf`, 파티션 3·복제 2)로 첫 전송 때 생긴다.
  첫 전송에 `UNKNOWN_TOPIC_OR_PARTITION ... retrying` 이 한 번 찍히는 것은 정상.
- MSK 보안 그룹이 EKS 서브넷 CIDR 의 9092 를 이미 연다 (review-service 와 같은 경로). 인증 없음.

## 무엇을 긁나 (match[])

| 선택자 | 10/10 시계열 수 |
| --- | --- |
| `{__name__="http_requests_total",app="sample-app"}` | 10 |
| `{__name__="http_request_duration_seconds_bucket",app="sample-app"}` | 100 |
| `{__name__=~"rollout_.+",name="sample-app"}` | 32 |
| `{__name__="argocd_app_info"}` | 5 |
| `{__name__=~"review_.+"}` | 약 280~330 |

합쳐서 15초마다 약 420~470개. `/federate` 는 형식 정보 없이(`untyped`) 내보내서 OTLP 에서는 전부 gauge 가 된다
(카운터 rate·히스토그램 계산은 받는 쪽에서 라벨 `le` 로). 원래 라벨(job·instance·pod 등)은 `honor_labels` 로 그대로.

## 메시지 키가 "aws-seoul" 인 이유 (파이프라인이 둘)

- `partition_metrics_by_resource_attributes` 는 키가 **resource attribute 전체의 해시**다 — 클러스터 이름이 아니고 resource(job·instance)마다 달라진다.
- 글자 그대로의 키는 `metrics.message_key_from_metadata_key` 뿐이고 값은 요청 메타데이터에서 온다. 메타데이터를 채우는
  processor(`partitioningprocessor`)는 0.162.0 기준 릴리스에 없다.
- 그래서 `metrics/scrape` 파이프라인이 OTLP 로 자기 자신(`127.0.0.1:4317`)에게 `cluster: aws-seoul` 헤더를 붙여 보내고,
  `metrics/kafka` 파이프라인의 OTLP receiver 가 `include_metadata` 로 받아 kafka exporter 가 그 값을 키로 쓴다.
  127.0.0.1 에만 열려 파드 밖에서는 못 들어온다.
- `metrics/kafka` 에는 batch 를 두지 않는다 — batch 는 `metadata_keys` 없이는 메타데이터(키)를 버린다.
- 시작할 때 `grpc: addrConn.createTransport failed to connect to {Addr: "127.0.0.1:4317"...} connection refused` 경고가
  한 번 찍힌다. exporter 가 receiver 보다 먼저 연결을 시도해서다. 곧 다시 붙는다.
- 파드가 재시작되면 그 순간 처리 중이던 배치(최대 15초 분량)는 버려진다. 1단계라 큐·재전송은 두지 않았다.

## 처음 켜기 (한 번만)

```bash
kubectl apply -f argocd/telemetry-collector-aws.yaml
kubectl -n argocd get application telemetry-collector-aws        # Synced / Healthy
kubectl -n monitoring get pod -l app=telemetry-collector          # Running 1/1
```

## 확인

### 1. collector 로그 — 긁기·내보내기

```bash
kubectl -n monitoring logs deploy/telemetry-collector --since=2m | grep -E '"debug"|error|Exporting failed'
```

- 15초마다 `"otelcol.component.id": "debug" ... "resource metrics": 8, "metrics": 50, "data points": 4xx` 한 줄 — 긁어서 kafka 파이프라인까지 왔다
- `error`·`Exporting failed` 가 없으면 Kafka 전송도 성공. 숫자로 보려면 collector 자체 지표:

```bash
kubectl -n monitoring port-forward deploy/telemetry-collector 8888:8888 &
curl -s localhost:8888/metrics | grep -E 'otelcol_exporter_(sent|send_failed)_metric_points\{exporter="kafka"'
# sent 가 계속 늘고 send_failed 가 없거나 0 이면 성공
```

### 2. 클러스터 안에서 토픽 읽기 — 메시지와 키

MSK 는 클러스터 안(EKS 서브넷)에서만 닿는다. 임시 파드로 읽고 끝나면 지워진다.

```bash
kubectl -n monitoring run kafka-check --rm -it --restart=Never --image=apache/kafka:3.9.1 -- \
  /opt/kafka/bin/kafka-console-consumer.sh \
    --bootstrap-server b-1.oneactionreview.lf4qfu.c4.kafka.ap-northeast-2.amazonaws.com:9092 \
    --topic telemetry.metrics --max-messages 3 --timeout-ms 60000 \
    --property print.key=true --property key.separator=' | '
```

기대: 줄마다 `aws-seoul | {"resourceMetrics":[{"resource":{"attributes":[...{"key":"cluster","value":{"stringValue":"aws-seoul"}},{"key":"env","value":{"stringValue":"aws"}}...`

(최신 것부터 기다리므로 15초 안에 나온다. 처음부터 보려면 `--from-beginning`.)

### 3. Prometheus 가 그대로인지

```bash
kubectl -n monitoring get pod prometheus-monitoring-kube-prometheus-prometheus-0   # RESTARTS·AGE 가 켜기 전과 같다
kubectl -n argocd get application monitoring-aws                                  # Synced / Healthy, 리비전 그대로
```

## 끄기·되돌리기

```bash
kubectl delete -f argocd/telemetry-collector-aws.yaml   # finalizer 로 Deployment·ConfigMap 도 지워진다
```

토픽은 남는다. 지우려면 위 임시 파드 방식으로 `kafka-topics.sh --delete --topic telemetry.metrics`.

## 리소스

requests `cpu 20m / memory 64Mi`, limits `cpu 200m / memory 128Mi`, `GOMEMLIMIT=100MiB`, memory_limiter 80%.
로컬(docker, 같은 이미지·같은 설정, 실제 /federate 응답 424 data points)에서 문제없이 돌았다.

## 다음 단계 (아직 안 함)

GKE(도쿄)·로컬 k3s(부산)에 같은 수집기를 `cluster=gcp-tokyo`·`local-busan` 으로. 그쪽은 MSK 에 닿는 경로가 먼저 필요하다.
