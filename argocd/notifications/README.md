# 배포 결과를 검토 서비스로 보내기 (Argo CD Notifications)

배포가 성공하거나 실패하면 Argo CD 가 검토 서비스에 알린다. 업무 DB 에 **baseline**(마지막으로 성공한 배포 설정)이 쌓여야, 다음 검토에서 "이전 배포와 비교하는" 규칙이 걸린다. DB 엔진을 바꾸거나 볼륨을 줄이는 것처럼 **지금 명세만 봐서는 알 수 없는 위험**이 그런 규칙이다.

## 무엇이 어디로 가나

```
Argo CD (argocd)  ──POST──>  Review API (platform)
                             http://platform.platform.svc.cluster.local:8080/webhooks/argocd
                             Authorization: Bearer <ARGOCD_WEBHOOK_TOKEN>
```

본문은 이렇게 간다.

```json
{
  "app": "sample-app",
  "env": "aws",
  "health": "Healthy",
  "images": ["ghcr.io/crystal-sbhackathon2026/sample-app:<병합 SHA>"],
  "revision": "<gitops 커밋 SHA>"
}
```

`images` 의 태그가 **병합 SHA** 라서, 검토 서비스가 이 값으로 "어느 검토의 결과가 배포됐는지" 를 찾는다. 그래서 `images` 는 빠지면 안 된다.

`app` 과 `env` 는 Application 의 annotation 에서 읽는다.

```yaml
metadata:
  annotations:
    oneaction.crystal/app: sample-app   # deploy.yaml 의 metadata.name 과 같아야 한다
    oneaction.crystal/env: aws          # target.env 와 같아야 한다
    notifications.argoproj.io/subscribe.on-deployed.review-api: ""
    notifications.argoproj.io/subscribe.on-health-degraded.review-api: ""
```

Application 이름(`sample-app-aws`)을 잘라 쓰지 않는 이유는, 앱 이름이 `deploy.yaml` 의 `metadata.name` 이라 Application 이름과 어긋날 수 있기 때문이다.

## 새 형식 `deployment.result/v1` (준비만 해둔 것)

김연재 요청(2026-10-09, [배포 실패 원인 분석 명세](https://app.notion.com/p/3f48bee9ada4819b8833d7f1704ba746))으로 **실패 증거를 같이 보내는 형식**을 준비했다. Argo CD 가 이미 들고 있는 오류 정보를 넘겨서, 검토 서비스가 "왜 실패했는지" 를 사용자에게 안내한다.

🔴 **아직 안 켰다.** 켜는 것은 김연재 수신 코드가 배포된 뒤다.

왜 순서가 중요한가 — `sync_failed` 는 **health 가 `Healthy` 일 수 있다.** 새 버전 적용이 실패하면 옛 버전이 그대로 떠 있기 때문이다. health 만 보는 지금 수신 코드에 먼저 켜면 **실패가 정상 baseline 으로 쌓인다.** 그러면 다음 검토가 잘못된 기준과 비교한다.

| | 지금 | 준비된 것 |
| --- | --- | --- |
| 템플릿 | `deploy-result` | `deploy-result-deployed` · `-degraded` · `-sync-failed` |
| 트리거 | `on-deployed` · `on-health-degraded` | 위 둘 + `on-sync-failed` |
| 구독 | 앞의 둘만 | 그대로 (새 트리거는 **구독 안 됨** → 평가되지 않아 아무것도 안 나간다) |

### 전환 절차 (김연재 수신 코드 배포 뒤 PR 하나)

1. `trigger.on-deployed` 의 `send: [deploy-result]` → `[deploy-result-deployed]`
2. `trigger.on-health-degraded` 의 `send: [deploy-result]` → `[deploy-result-degraded]`
3. Application 에 `notifications.argoproj.io/subscribe.on-sync-failed.review-api: ""` 추가
4. `template.deploy-result` 삭제
5. 로컬 k3s 에 일부러 실패를 넣어 세 알림이 실제로 가는지 확인

### 🔴 템플릿이 셋인 이유 — `event_type` 을 상태에서 유도하지 않는다

Notifications 에는 템플릿 include 가 없어서 본문을 셋으로 베꼈다. 하나로 합치고 `event_type` 을 앱 상태에서 유도할 수도 있지만 **그러면 안 된다.**

`health` · `sync_status` · `operation.phase` 는 **서로 다른 관측값**이다. 보내는 쪽이 하나의 성공/실패로 합치면 받는 쪽이 다시 나눌 수 없다. 실제로 이런 조합이 나온다.

| | `health` | `operation.phase` | 무엇인가 |
| --- | --- | --- | --- |
| `sync_failed` | **Healthy** | Failed | 적용이 실패해 옛 버전이 그대로 떠 있다 |
| `health_degraded` | Degraded | **Succeeded** | 적용은 됐는데 새 파드가 못 떴다 |

그래서 `event_type` 은 **어느 트리거가 울렸는지**로만 정하고 트리거별 템플릿에 고정값으로 박는다.

본문 셋이 어긋나면 수신 쪽이 알림 종류마다 다른 필드를 받고, 그건 알림이 실제로 갈 때까지 아무도 모른다. 그래서 검사 스크립트를 뒀다. **템플릿을 고치면 셋 다 고치고 이걸 돌린다.**

```bash
python argocd/notifications/check-templates.py
# 템플릿 3개 - event_type 만 다르고 나머지는 같다
```

### 중첩 필드는 `dig` 로 읽는다

`.app.status.health.message` 처럼 바로 타고 들어가면 중간 단계가 없을 때 템플릿이 nil pointer 로 죽고, **그러면 알림이 조용히 안 간다.** `dig` 는 없으면 기본값을 준다.

v3.5.4 에서 쓸 수 있는 것을 실제로 확인했다 (`toJson` · `default` · `dig` · `list` · `now | date`). 김연재가 물어본 "JSON 직렬화 함수가 있나" 의 답은 **`toJson` 이 된다** 이고, `images` 에 이미 운영에서 쓰고 있다.

```bash
# 보내지 않고 렌더링만 본다 - --recipient 기본값이 console:stdout 이다
kubectl -n argocd exec deploy/argocd-notifications-controller --   argocd admin notifications template notify deploy-result-deployed sample-app-aws
```

### `cluster_id` 는 이름이 없으면 주소로 떨어진다

`destination.name` 이 비면 `destination.server` 를 쓴다. 지금 `sample-app-aws` 는 이름이 없어서(`server: kubernetes.default.svc`) **실제로 이 길로 간다.** 로컬·GCP 는 이름(`crystal-busan` · `tokyo-gke`)으로 등록돼 있어 이름이 온다.

### `revision` 과 `operation.revision` 은 다른 값이다

실측 (2026-10-09 `sample-app-aws`):

```
revision           ff0f310   지금 무엇과 비교해 Synced 인가
operation.revision ad946b1   마지막 적용 작업이 실제로 쓴 리비전
```

매니페스트가 안 바뀐 커밋이 올라오면 Argo CD 는 새 작업 없이 `revision` 만 올린다. **실패 원인을 찾을 때 봐야 하는 것은 `operation.revision` 이다.** 그래서 `revision` 을 실패한 작업 리비전으로 덮지 않는다.

### 크기

| Application | 본문 |
| --- | --- |
| `sample-app-aws` | 2.3 KB |
| `review-service-aws` | 6.0 KB |

김연재가 둔 상한 256 KiB 의 2% 수준이다. 커지는 쪽은 `resources` 와 `operation.resources` 라 리소스 수에 비례한다.

### 샘플

`samples/deployed.json` — **실제 Application 에서 렌더링한 것**이다. 손으로 쓴 예시가 아니다.

실패 쪽 샘플은 값이 실제 실패에서 나와야 의미가 있다. 김연재 수신 코드가 올라간 뒤 로컬 k3s 에 실패를 주입해서 같이 확인하고 그때 추가한다 — 멀쩡한 앱으로 렌더링하면 `event_type` 만 `sync_failed` 이고 나머지는 성공 값이라 오히려 오해를 만든다.

## 언제 보내나

| 트리거 | 조건 | 중복 방지 |
| --- | --- | --- |
| `on-deployed` | 동기화가 끝나고(`Succeeded`) Healthy | 동기화한 리비전당 한 번 |
| `on-health-degraded` | Degraded | 리비전당 한 번 |
| `on-sync-failed` | 작업 phase 가 `Failed` 또는 `Error` | **작업 시작 시각**당 한 번 (아직 구독 안 됨) |

`Progressing` 같은 중간 상태는 보내지 않는다.

`on-sync-failed` 의 중복 방지만 리비전이 아니라 **작업 시작 시각**(`operationState.startedAt`)이다. phase 가 `Error` 면 `syncResult` 가 아예 없어서 리비전으로는 중복 방지 키가 빈 값이 된다. `startedAt` 은 작업마다 다르고 `operationState` 가 있으면 반드시 있다. 김연재의 중복 판정 키에도 `started_at` 이 들어간다.

**알림이 두 번 갈 수 있다.** `commit_overlay` 와 CI 가 각각 gitops 에 커밋하므로(간격 약 44초) Argo CD 가 두 번 동기화할 수 있고, 그때 첫 알림은 overlay 만 반영된 상태라 `images` 가 옛 태그다. 중복 방지를 `images` 기준으로 바꾸면 그건 걸러지지만, **설정만 바뀌고 이미지가 같은 배포는 알림이 아예 안 가서 baseline 이 갱신되지 않는다.** 그래서 리비전 기준으로 두고, 같은 `(app, env, 이미지 태그)` 알림은 Review API 가 한 번만 기록한다 (2026-10-09 김혜연 합의).

## 적용

```bash
kubectl apply -f argocd/notifications/secretstore.yaml
kubectl apply -f argocd/notifications/externalsecret.yaml
kubectl apply -f argocd/notifications/notifications-cm.yaml
kubectl apply -f argocd/sample-app-aws.yaml
```

컨트롤러는 ConfigMap 변경을 스스로 다시 읽는다. 재시작하지 않아도 된다.

### 토큰은 ESO 가 넣는다 (2026-10-09 전환 완료)

`argocd` 네임스페이스 **전용 ESO 컨트롤러**가 생겨서 손으로 넣을 필요가 없어졌다 (박찬건, `-Terraform-infrastructure#15`). 컨트롤러가 네임스페이스마다 하나씩이고 각자 ServiceAccount·Pod Identity 를 쓴다.

| 컨트롤러 | 맡는 네임스페이스 | ServiceAccount |
| --- | --- | --- |
| `external-secrets` | `platform` | `external-secrets` |
| `external-secrets-argocd` | `argocd` | `external-secrets-argocd` |

`argocd` 쪽 역할은 `oneaction/review-service` **하나만** 읽도록 제한돼 있다. `ClusterSecretStore` 는 여전히 필요하지 않다.

`creationPolicy: Merge` 라서 Argo CD 설치가 만든 `argocd-notifications-secret` 을 가져가지 않고 키 하나만 더한다. 설치가 붙인 라벨 3개가 그대로 남는다. `deletionPolicy: Retain` 이라 ExternalSecret 을 지워도 키는 남는다.

**ESO 가 실제로 그 키를 소유하는지 확인한 방법** (2026-10-09, 같은 값이라 겹쳐 써도 티가 안 나서 한 번 비워봤다)

```bash
# ① 키를 지운다
kubectl -n argocd patch secret argocd-notifications-secret --type json \
  -p '[{"op":"remove","path":"/data/ARGOCD_WEBHOOK_TOKEN"}]'

# ② 컨트롤러가 다시 가져오는지 — 시각이 ①과 맞아야 한다
kubectl -n external-secrets logs deploy/external-secrets-argocd --tail=20 | grep "fetching secret value"

# ③ 이벤트에도 남는다
kubectl -n argocd get events --field-selector involvedObject.name=argocd-notifications
#   Normal  Updated  externalsecret/argocd-notifications  secret updated
```

지우자마자 ESO 가 **스스로 감지해** Secrets Manager 에서 다시 가져왔다(`force-sync` annotation 을 붙이기 전에 이미 복구됐다). 정기 갱신 주기는 1시간이지만 대상 Secret 이 바뀌면 바로 반응한다.

> `metadata.managedFields` 로는 소유자를 알 수 없다. ESO 가 server-side apply 를 쓰지 않아 비어 있다.

급히 ESO 를 건너뛰어야 하면(컨트롤러 장애 등) 이 방법이 있다. **값이 화면이나 명령 기록에 남지 않도록 파일로 넘긴다.**

```bash
aws secretsmanager get-secret-value \
  --secret-id oneaction/review-service --profile crystal --region ap-northeast-2 \
  --query SecretString --output text \
| python -c "import sys,json,base64;print(json.dumps({'data':{'ARGOCD_WEBHOOK_TOKEN':base64.b64encode(json.load(sys.stdin)['ARGOCD_WEBHOOK_TOKEN'].encode()).decode()}}))" \
> patch.json

kubectl -n argocd patch secret argocd-notifications-secret --type merge --patch-file patch.json
rm patch.json
```

손으로 넣어도 다음 갱신에서 ESO 가 Secrets Manager 값으로 되돌린다. **값을 바꿔야 하면 Secrets Manager 를 고쳐야 한다.**

## 확인

```bash
# 컨트롤러가 보냈는지
kubectl -n argocd logs deploy/argocd-notifications-controller --tail=50 | grep -i "sending\|POST"

# 어떤 리비전까지 보냈는지
kubectl -n argocd get application sample-app-aws \
  -o jsonpath='{.metadata.annotations.notified\.notifications\.argoproj\.io}'

# argocd 에서 Review API 에 닿는지
kubectl -n argocd run nettest --rm -it --image=curlimages/curl:8.11.1 -- \
  curl -s -o /dev/null -w '%{http_code}\n' http://platform.platform.svc.cluster.local:8080/healthz
```

같은 리비전을 다시 보내게 하려면 발송 기록을 지운다.

```bash
kubectl -n argocd patch application sample-app-aws --type json \
  -p '[{"op":"remove","path":"/metadata/annotations/notified.notifications.argoproj.io"}]'
```

## 구독하지 않는 것

`review-service-aws` 는 구독하지 않는다. `app` 값이 `deploy.yaml` 의 `metadata.name` 이어야 하는데 review-service 레포에는 `deploy.yaml` 이 없다. 검토 대상이 아닌 앱의 baseline 이 쌓이면 혼란스럽다.
