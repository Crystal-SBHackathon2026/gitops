#!/usr/bin/env python3
"""deployment.result/v1 템플릿 셋이 서로 어긋나지 않았는지 본다.

Argo CD Notifications 에는 템플릿 include 가 없어서 세 알림 종류의 본문을
베껴 쓸 수밖에 없다. 어긋나면 수신 쪽이 알림 종류마다 다른 필드를 받게 되고,
그건 알림이 실제로 갈 때까지 아무도 모른다.

event_type 한 줄만 다르고 나머지는 글자까지 같아야 한다.

    python argocd/notifications/check-templates.py
"""

import re
import sys
from pathlib import Path

# 윈도우 기본 콘솔은 cp949 라 한국어·em dash 를 출력하다 죽는다.
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

CM = Path(__file__).with_name("notifications-cm.yaml")

# 알림 종류마다 event_type 에 박혀 있어야 하는 값
EXPECTED_EVENT_TYPE = {
    "template.deploy-result-deployed": "deployed",
    "template.deploy-result-degraded": "health_degraded",
    "template.deploy-result-sync-failed": "sync_failed",
}

EVENT_TYPE_LINE = re.compile(r'^\s*"event_type":\s*"(?P<value>[^"]*)",?\s*$')


def template_bodies(text):
    """ConfigMap 의 data 키별 블록 스칼라 내용을 돌려준다.

    yaml 로 읽지 않는 이유: 이 파일의 값에는 Go 템플릿의 {{ }} 가 들어 있고,
    검사하려는 것이 바로 그 글자 자체다. 파서를 거치면 들여쓰기가 정규화돼
    "글자까지 같은가" 를 못 본다.
    """
    bodies = {}
    key = None
    lines = []
    for line in text.splitlines():
        header = re.match(r"^  (template\.[\w.-]+): \|\s*$", line)
        if header:
            if key is not None:
                bodies[key] = lines
            key, lines = header.group(1), []
            continue
        if key is None:
            continue
        # 블록이 끝나는 지점: 들여쓰기가 4칸 미만인 빈 줄 아닌 줄
        if line.strip() and not line.startswith("    "):
            bodies[key] = lines
            key, lines = None, []
            continue
        lines.append(line)
    if key is not None:
        bodies[key] = lines
    return bodies


def main():
    text = CM.read_text(encoding="utf-8")
    bodies = template_bodies(text)

    problems = []

    missing = [k for k in EXPECTED_EVENT_TYPE if k not in bodies]
    if missing:
        for key in missing:
            problems.append(f"{key} 가 {CM.name} 에 없다")
        report(problems)
        return 1

    # 1. 각 템플릿의 event_type 이 제 값으로 박혀 있는가
    normalized = {}
    for key, expected in EXPECTED_EVENT_TYPE.items():
        found = None
        stripped = []
        for line in bodies[key]:
            match = EVENT_TYPE_LINE.match(line)
            if match:
                found = match.group("value")
                continue  # 비교에서는 이 줄을 뺀다
            stripped.append(line)
        if found is None:
            problems.append(f'{key} 에 "event_type" 줄이 없다')
        elif found != expected:
            problems.append(f'{key} 의 event_type 이 "{found}" 다 — "{expected}" 여야 한다')
        normalized[key] = stripped

    # 2. event_type 을 뺀 나머지가 글자까지 같은가
    keys = list(EXPECTED_EVENT_TYPE)
    base = keys[0]
    for key in keys[1:]:
        if normalized.get(key) != normalized.get(base):
            problems.append(
                f"{key} 의 본문이 {base} 와 다르다 (event_type 줄 제외). "
                f"줄 수 {len(normalized.get(key, []))} vs {len(normalized.get(base, []))}"
            )
            for i, (a, b) in enumerate(zip(normalized[base], normalized[key]), 1):
                if a != b:
                    problems.append(f"  첫 차이 {i}번째 줄\n    {base}: {a!r}\n    {key}: {b!r}")
                    break

    return report(problems)


def report(problems):
    if problems:
        print("템플릿이 어긋났다:\n", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"템플릿 {len(EXPECTED_EVENT_TYPE)}개 — event_type 만 다르고 나머지는 같다")
    return 0


if __name__ == "__main__":
    sys.exit(main())
