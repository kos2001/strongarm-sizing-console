---
name: strongarm-lessons
description: "Use whenever answering StrongARM console (comparator/VCO) requests — accumulated failure lessons from the self-improvement loop (scripts/agent_selftest.py). Each entry is a REAL mistake an agent made on this console, its measured consequence, and the rule that prevents it. Read before proposing sizes or interpreting measurements."
version: 1.0.0
author: self-improvement loop
license: MIT
metadata:
  hermes:
    tags: [semiconductor, strongarm, lessons, self-improvement]
    related_skills: [strongarm-console, strongarm-design-recipes]
---

# Lessons — 실패에서 축적된 규칙

이 파일은 `scripts/agent_selftest.py`(자기개선 루프)가 실패를 감지할 때마다
항목이 추가된다. 사람이 주기적으로 검토·정제한다.

## L1 · 직관 사이징은 실측으로 뒤집힌다 (2026-07-12, 수동 발견)

- **증상**: "오프셋 마진이 크니 input m 을 절반으로, ncc 를 강화" — 논리적으로
  들리는 제안이 실측에서 530→**1063 ps 악화**.
- **원인**: input m 축소는 gm 을 직접 깎아 재생 이득 손실이 캡 절감보다 크다.
- **규칙**: 사이징 제안은 반드시 `strongarm_run_sim` 실측 후에만 제시.
  두 스펙 이상 위반이면 손대지 말고 `strongarm_optimize` 위임.

## L2 · VCO `per` 측정은 5주기 구간이다 (2026-07-12, edit 검증에서 발견)

- **증상**: 덱의 `meas per`(RISE=3..8)를 1주기로 해석해 주파수를 5배 낮게
  (467 MHz vs 실제 2.336 GHz) 보고. 덱 수정 자체는 정확했음.
- **규칙**: VCO 덱에서 **f_osc = 5/per**. 상대 비교만 필요한 경우에도 절대값을
  보고할 땐 반드시 환산하라. (덱 주석에도 명시되어 있다 — 읽어라.)

<!-- selftest 가 새 교훈을 이 아래에 append 한다 -->

## L3 · MCP 도구 추가 후 게이트웨이 재시작 필수 (2026-07-12, selftest 가 발견 → 해결)

- **증상**: mcp_server.py 에 새 도구(design_brief)를 추가했는데 에이전트가
  "도구 목록에 없다"며 우회 — hermes 게이트웨이 데몬이 구 툴셋을 캐시.
- **해결**: `launchctl kickstart -k gui/$(id -u)/ai.hermes.gateway-strong-arm`
  → 재실행에서 129s 실패가 30s PASS 로. **MCP 도구를 바꾸면 게이트웨이도
  재시작하라** (콘솔 서버 재시작만으로는 부족).

## L4 · 반환 덱은 완전해야 한다 (2026-07-12, selftest 가 발견 → 해결)

- **증상**: 측정 결과 표는 정확했지만 ```spice 블록의 덱이 축약되어 독립
  실행 시 tdec 측정 실패 — "검증됐다"는 주장과 재현 불가능한 덱의 조합.
- **해결**: edit 역할 규칙에 "원본 전 라인(.control/.end 포함) + 수정분,
  생략(...) 금지" 명시 → 재실행 PASS. 덱을 제시할 땐 항상 그대로 실행
  가능한 완전본이어야 한다.

## L5 · 게이트웨이 재시작은 진행 중인 에이전트 콜을 죽인다 (2026-07-13, selftest 오탐에서)

- **증상**: selftest 실행 중 게이트웨이를 재시작하자 진행 중 과제가
  'Remote end closed connection' 으로 실패 — 회귀가 아니라 운영 간섭.
- **규칙**: 게이트웨이/콘솔 재시작은 셀프테스트·에이전트 턴이 없는
  시점에 하라. selftest 실패를 보면 먼저 answer 필드에서 연결 에러인지
  확인하고, 인프라 원인이면 해당 과제만 재실행해 판정하라.
