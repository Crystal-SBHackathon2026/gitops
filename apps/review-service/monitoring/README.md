# 검토 서비스 모니터링 (`apps/review-service/monitoring/`)

review-api·review-worker 지표(Prometheus)와 업무 DB(Postgres) 대시보드. 10/09 에 아래 순서대로 켰다 (1·2번 완료, 3번 이 디렉터리를 상위 kustomization 에 추가).

| 파일 | 내용 |
|---|---|
| `servicemonitors.yaml` | review-api `Service platform :http(8080)/metrics`, review-worker `Service review-worker-metrics :metrics(9100)/metrics`, 30초 |
| `grafana-datasource.yaml` | ExternalSecret → Secret `review-db-grafana-datasource` (`grafana_datasource: "1"`). 데이터소스 `review-db`(uid 같음), 읽기 전용 `grafana_ro` |
| `dashboards/platform-overview.json` | **플랫폼 현황** (Prometheus) — 상태별 검토 수, needs_human 대기, API 요청량·5xx·p95, 웹훅 결과, Kafka 발행 실패, consumer lag, 노드별 p95, judge 실패, sweep 회수, LLM 호출·토큰 |
| `dashboards/commit-timeline.json` | **커밋 타임라인** (업무 DB) — SHA·PR 번호로 생성 → 판정 → 사람 결정 → 병합 → gitops 커밋 → 배포 알림, 최근 50건 |
| `kustomization.yaml` | 위 두 JSON 을 ConfigMap 으로 (`grafana_dashboard: "1"`, 폴더 `platform`) |

워커 지표 포트(`containerPort: 9100`)와 `Service review-worker-metrics` 는 `worker.yaml` 에 있다 (그건 지금 적용돼도 된다).

## 켜는 순서

1. **읽기 전용 DB 사용자** — 사람이 RDS 에 마스터 계정으로 접속해 한 번 (비밀번호는 아래 2번에서 만든 값)
   ```sql
   CREATE ROLE grafana_ro LOGIN PASSWORD '<2번의 값>';
   GRANT CONNECT ON DATABASE oneaction_review TO grafana_ro;
   GRANT USAGE ON SCHEMA public TO grafana_ro;
   GRANT SELECT ON reviews, deploy_events, spec_intakes, baselines TO grafana_ro;
   ALTER ROLE grafana_ro SET default_transaction_read_only = on;
   ```
2. **Secrets Manager** `oneaction/review-service` 에 `GRAFANA_DB_PASSWORD` 추가 — PR 본문의 명령 (값을 화면에 내지 않는다)
3. `apps/review-service/kustomization.yaml` 의 `resources` 에 `- monitoring` 추가
4. 확인: Prometheus Targets 에 `serviceMonitor/platform/review-api`·`review-worker` UP, Grafana `platform` 폴더에 대시보드 2개, 데이터소스 `review-db` 테스트 OK

## 설치된 스택과 맞춘 값 (10/09 09:48Z kube-prometheus-stack, 릴리스 `monitoring`)

- Prometheus `serviceMonitorSelector`·`serviceMonitorNamespaceSelector` 가 `{}` — 라벨과 무관하게 모든 네임스페이스의 ServiceMonitor 를 긁는다
- Grafana 13.2.3 sidecar: 대시보드·데이터소스 모두 `NAMESPACE=ALL`, `FOLDER_ANNOTATION=grafana_folder` — platform 네임스페이스의 ConfigMap·Secret 을 읽는다
- 데이터소스 타입 `grafana-postgresql-datasource` (Grafana 10.3 이후 이름)
- RDS 보안 그룹은 EKS 프라이빗 서브넷(10.0.32.0/19, 10.0.64.0/19)의 5432 를 허용 — Grafana 파드도 그 안에서 뜬다

## 배포 어노테이션 — 앱 대시보드에서 갖다 쓰기

데이터소스 `review-db` 로 대시보드 설정 → Annotations → New 에 이 쿼리를 넣으면 배포 Healthy·Degraded 시각이 세로선으로 나온다.

```sql
SELECT received_at AS time, app || ' ' || kind || ' ' || left(image_tag, 7) AS text, app, target_env
FROM deploy_events WHERE $__timeFilter(received_at)
```

한 앱만 보려면 `AND app = 'sample-app'` 을 더한다.

## 대시보드 고치기

JSON 은 Grafana 에서 고친 뒤 Export → JSON 으로 이 파일을 덮는다. 데이터소스는 Prometheus 는 변수 `${datasource}`, 업무 DB 는 uid `review-db` 로 찾는다.
