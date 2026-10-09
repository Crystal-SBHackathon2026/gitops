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

## 언제 보내나

| 트리거 | 조건 | 중복 방지 |
| --- | --- | --- |
| `on-deployed` | 동기화가 끝나고(`Succeeded`) Healthy | 동기화한 리비전당 한 번 |
| `on-health-degraded` | Degraded | 리비전당 한 번 |

`Progressing` 같은 중간 상태는 보내지 않는다.

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
