#!/usr/bin/env bash
# 카나리 분석용 부하 장치 — 노트북에서 도는 쪽.
#
# apps/loadgen/ 의 클러스터 안 부하 장치와 같은 일을 한다. 이쪽은
#   · 클러스터 접근(kubectl)이 없어도 된다 — 공개 주소로 바로 쏜다
#   · 리허설·시험 때 켰다 껐다 하기 쉽다
#   · 1초마다 현재 성공/실패 비율을 찍어 준다 (중단되는 순간이 눈에 보인다)
#
# 왜 필요한가: 에러율 지표는 비율이라 분모(요청 수)가 없으면 판정을 못 한다.
# 요청이 없으면 결과가 0 으로 나와 망가진 버전이 그대로 승격된다 (sample-app #42 실측).
#
# 🔴 순차 루프로는 목표 속도가 안 나온다.
#   서울 ALB 는 왕복이 300~500ms 라, 요청을 하나씩 보내면 아무리 sleep 을 줄여도
#   초당 2건을 못 넘는다 (10/10 실측: 목표 5건, 실제 1.5건).
#   그래서 먼저 왕복시간을 재고, 필요한 만큼 일꾼을 동시에 띄운다.
#
# 쓰는 법
#   ./scripts/loadgen.sh                 # 서울 ALB 로 약 5 요청/초
#   ./scripts/loadgen.sh local           # 부산 로컬 (localhost:8081)
#   ./scripts/loadgen.sh <주소>          # 임의 주소
#   RPS=20 ./scripts/loadgen.sh          # 초당 요청 수 바꾸기
#   SECS=90 ./scripts/loadgen.sh         # 90초만 돌리고 요약 찍고 끝낸다
#   Ctrl-C 로 멈춘다.
#
# ⚠️ 실제로 나오는 속도에는 천장이 있다. git-bash(Windows)는 curl 프로세스 하나
# 띄우는 데만 300ms 넘게 쓴다. 일꾼을 늘려도 서로 경쟁해서 **3~5 요청/초**에서
# 더 안 올라간다 (10/10 실측: 목표 12 → 실제 3.5).
# 그래도 충분하다 — 분석 창 30초에 100건 넘게 들어가고, 캐너리 파드로 그 2/3 이
# 간다. 30% 실패 버전이면 비율이 또렷하게 찍힌다. 더 센 부하가 필요하면
# apps/loadgen/ 의 클러스터 안 장치를 쓰면 된다 (거기는 프로세스 생성이 싸다).
set -uo pipefail

SEOUL="http://k8s-sampleap-sampleap-88af4f1f82-400100408.ap-northeast-2.elb.amazonaws.com"
LOCAL="http://localhost:8081"

case "${1:-seoul}" in
  seoul|aws|"") BASE="$SEOUL" ;;
  local|busan)  BASE="$LOCAL" ;;
  *)            BASE="${1%/}" ;;
esac

RPS="${RPS:-5}"

# 🔴 /healthz 가 아니라 /api/info 다. 분석 쿼리가 헬스체크를 빼고 세고,
# FAIL_RATE 장애 주입이 걸리는 것도 이 경로다.
URL="$BASE/api/info"

echo "대상   $URL"
printf "한 바퀴 비용 재는 중... "
# 🔴 curl 의 %{time_total}(왕복시간)만 재면 모자란다. 한 바퀴에는 **curl 프로세스를
# 띄우는 비용**도 들어가고, 그게 왕복보다 클 때가 있다 (10/10 실측: 왕복 38ms 인데
# 한 바퀴는 310ms — Windows git-bash 의 프로세스 생성 비용). 그래서 벽시계로 잰다.
#   그렇게 안 쟀더니 목표 5건/초에 실제 3.2건/초가 나왔다.
# 첫 번째는 DNS·연결 설정이 섞여 느리므로 버리고 4번을 잰다.
curl -s -o /dev/null --max-time 5 "$URL" >/dev/null 2>&1
_t0=$(date +%s%N 2>/dev/null)
for _ in 1 2 3 4; do curl -s -o /dev/null --max-time 5 "$URL" >/dev/null 2>&1; done
_t1=$(date +%s%N 2>/dev/null)
RTT=$(awk -v a="${_t0:-0}" -v b="${_t1:-0}" 'BEGIN{
  d = (b - a) / 4e9
  if (d <= 0 || d > 5) d = 0.3     # date +%s%N 을 못 쓰는 환경이면 적당히 잡는다
  printf "%.3f", d
}')
echo "${RTT}초"

# 일꾼 수 = 목표 속도 x 한 바퀴 비용. 한 바퀴가 짧으면 한 명으로 충분하고,
# 비싸면(멀거나 프로세스 생성이 느리면) 여러 명이 동시에 돌아야 속도가 나온다.
# 8명에서 끊는다. 그 위로는 서로 경쟁해 한 바퀴가 더 비싸지기만 한다.
WORKERS=$(awk -v r="$RPS" -v t="$RTT" 'BEGIN{
  w = int(r * t + 0.999)
  if (w < 1) w = 1
  if (w < 1) w = 1
  if (w > 8) w = 8
  print w
}')
# 각 일꾼이 쉬는 간격. 한 바퀴에 (비용 + 간격) 이 걸리므로 비용을 빼야
# 전체 합이 목표 속도가 된다. 너무 0 에 붙으면 CPU 만 먹으므로 0.01 아래로는 안 간다.
GAP=$(awk -v r="$RPS" -v w="$WORKERS" -v t="$RTT" 'BEGIN{
  g = w/r - t
  if (g < 0.01) g = 0.01
  printf "%.3f", g
}')

echo "속도   약 ${RPS} 요청/초 목표 (일꾼 ${WORKERS}명 · 한 바퀴 ${RTT}초 + 쉼 ${GAP}초)"
echo "멈추기 Ctrl-C"
echo

PIDS=""
STARTED=$(date +%s)
TMP=$(mktemp -d)
LOG="$TMP/log"
: > "$LOG"

cleanup() {
  trap - INT TERM EXIT
  # 일꾼부터 정리한다. 안 그러면 백그라운드 루프가 남아 계속 요청을 보낸다.
  # ⚠️ 프로세스 그룹째(kill -- -PID) 보내지 않는다. 대화형이 아닌 셸에서는
  # 백그라운드 작업이 제 그룹을 안 갖는 일이 있어, 자기 자신까지 죽는다.
  for p in $PIDS; do kill "$p" 2>/dev/null; done
  # ⚠️ 여기서 wait 를 부르지 않는다. 일꾼이 curl 중에 죽으면 그 curl 이 고아로
  # 남아 wait 가 안 돌아오고, 합계가 영영 안 찍힌다 (10/10 실측).
  # ⚠️ grep -c 는 0건일 때 "0" 을 찍고 **종료코드 1** 을 낸다.
  # $(grep -c ... || echo 0) 으로 쓰면 "0\n0" 이 되어 산술식이 깨진다 (실제로 겪었다).
  # awk 로 세면 그 함정이 없다.
  ok=$(awk '/^1/{n++} END{print n+0}' "$LOG" 2>/dev/null)
  bad=$(awk '/^0/{n++} END{print n+0}' "$LOG" 2>/dev/null)
  ok=${ok:-0}; bad=${bad:-0}
  total=$((ok + bad))
  echo
  echo "────────────────────────────────"
  echo "합계  ${total}건 · 정상 ${ok} · 실패 ${bad}"
  [ "$total" -gt 0 ] && awk -v b="$bad" -v t="$total" \
    'BEGIN{printf "에러율 %.3f\n", b/t}'
  rm -rf "$TMP"
  exit 0
}
trap cleanup INT TERM EXIT

# 일꾼들. 한 줄 "1"(정상) 또는 "0"(실패) 을 공용 파일에 덧붙인다.
# 두 글자짜리 덧붙이기라 섞여 깨질 일이 없다.
i=0
while [ "$i" -lt "$WORKERS" ]; do
  (
    while true; do
      code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 3 "$URL" || echo 000)
      if [ "$code" = "200" ]; then echo 1 >> "$LOG"; else echo 0 >> "$LOG"; fi
      sleep "$GAP"
    done
  ) &
  PIDS="$PIDS $!"
  i=$((i + 1))
done

# 1초마다 그 사이에 쌓인 것만 본다.
SECS="${SECS:-0}"
[ "$SECS" -gt 0 ] && echo "(${SECS}초 뒤 자동으로 끝납니다)" && echo
seen=0
while true; do
  sleep 1
  if [ "$SECS" -gt 0 ] && [ $(( $(date +%s) - STARTED )) -ge "$SECS" ]; then
    cleanup
  fi
  # ⚠️ 한 바퀴에 프로세스를 적게 띄운다. 전에는 wc + tail + awk + date 로 넷을
  # 띄웠는데, git-bash 에서는 그 비용이 일꾼들과 경쟁해 출력이 2~3초에 한 번씩만
  # 나왔다. 지금은 awk 하나가 세는 일과 찍는 일을 같이 한다.
  # 마지막 줄에 "총 줄 수" 를 내보내고, 그 앞줄이 화면에 찍을 내용이다.
  out=$(awk -v seen="$seen" -v t="$(date +%H:%M:%S)" '
    { n++; if (n > seen) { w++; if (/^1/) o++ } }
    END {
      if (w > 0) printf "%s  %3d건  정상 %3d  실패 %3d  에러율 %.2f\n", t, w, o+0, w-o, (w-o)/w
      print n+0
    }' "$LOG")
  now=${out##*$'\n'}          # 마지막 줄 = 총 줄 수
  line=${out%$'\n'*}          # 그 앞 = 찍을 내용 (없으면 총 줄 수와 같다)
  if [ "$now" != "$seen" ]; then
    [ "$line" != "$now" ] && printf '%s\n' "$line"
    seen=$now
  fi
done
