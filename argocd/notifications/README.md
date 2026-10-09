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
kubectl apply -f argocd/notifications/notifications-cm.yaml
kubectl apply -f argocd/sample-app-aws.yaml
```

컨트롤러는 ConfigMap 변경을 스스로 다시 읽는다. 재시작하지 않아도 된다.

### 토큰 넣기 — 지금은 손으로 넣는다

ESO 로 넣으려 했지만 **지금은 안 된다.** 외부 시크릿 컨트롤러가 `platform` 네임스페이스에만 걸려 있다.

```
--namespace=platform
--enable-cluster-store-reconciler=false
```

`argocd` 네임스페이스의 `SecretStore`·`ExternalSecret` 은 컨트롤러가 보지 않아 상태조차 붙지 않는다. `ClusterSecretStore` CRD 도 설치돼 있지 않다. 그래서 `secretstore.yaml` 과 `externalsecret.yaml` 은 **자리만 만들어 두고 적용하지 않는다.**

그동안은 Secrets Manager 에서 읽어 직접 넣는다. **값이 화면이나 명령 기록에 남지 않도록 파일로 넘긴다.**

```bash
aws secretsmanager get-secret-value \
  --secret-id oneaction/review-service --profile crystal --region ap-northeast-2 \
  --query SecretString --output text \
| python -c "import sys,json,base64;print(json.dumps({'data':{'ARGOCD_WEBHOOK_TOKEN':base64.b64encode(json.load(sys.stdin)['ARGOCD_WEBHOOK_TOKEN'].encode()).decode()}}))" \
> patch.json

kubectl -n argocd patch secret argocd-notifications-secret --type merge --patch-file patch.json
rm patch.json
```

`argocd-notifications-secret` 은 Argo CD 설치가 만들어 둔 Secret 이다. `patch` 로 키만 더해야 설치가 붙인 라벨이 유지된다.

인프라에서 ESO 범위를 넓히면(`--namespace` 제거 또는 `argocd` 추가) 두 파일을 적용하고 손으로 넣은 키를 ESO 에 넘긴다.

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
