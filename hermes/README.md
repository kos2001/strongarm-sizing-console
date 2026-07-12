# Hermes agent assets — StrongARM Sizing Console

이 디렉토리는 콘솔을 **hermes-agent**로 구동하기 위한 자산이다: MCP 서버
등록, 전용 프로파일 구성, 에이전트 스킬. 웹 콘솔의 🤖 자연어 패널은 이
프로파일의 api_server 를 `/api/agent/chat` 로 프록시한다.

## 1) MCP 서버 등록

MCP 서버 자체는 레포 루트의 `mcp_server.py`(46 tools, 의존성 없음)다.
활성 프로파일에 등록:

```sh
./hermes/register.sh              # 또는 수동으로:
hermes mcp add strongarm --command python3 \
  --args "$(pwd)/mcp_server.py"   # 레포 루트에서
hermes mcp test strongarm         # 46개 tool 발견 확인
```

- 툴들은 `$STRONGARM_API`(기본 `http://127.0.0.1:8770`)의 백엔드로 프록시
  하므로 **콘솔 서버가 떠 있어야 한다** (`webapp/server.py` 또는 launchd).
- 비대화식 셸에서는 확인 프롬프트를 `echo "Y" | hermes mcp add …` 로 통과.

## 2) 전용 프로파일 (`strong-arm`)

콘솔 전용 api_server 인스턴스(포트 8645 사용 예):

```sh
hermes profile create strong-arm
hermes profile use strong-arm
# config.yaml: api_server.port=8645, 모델/프로바이더 설정
hermes mcp add strongarm --command python3 --args <repo>/mcp_server.py
```

**주의(실측 gotcha)**: 프로파일 `.env` 의 `API_SERVER_KEY` 가 `config.yaml`
의 토큰을 **덮어쓴다** — 둘을 같게 유지하지 않으면 401. 웹 콘솔 프록시는
`~/.hermes/profiles/strong-arm/config.yaml` 에서 포트/토큰을 자동으로 읽고,
`STRONGARM_AGENT_URL`/`STRONGARM_AGENT_TOKEN` 환경변수로 재정의할 수 있다.

## 3) 스킬

`hermes/skills/` 아래 두 개 — 프로파일의 skills 디렉토리에 복사(또는 심링크)
하면 에이전트가 로드한다:

| 스킬 | 용도 |
|---|---|
| `strongarm-console` | 콘솔을 MCP 로 구동하는 법: 46-tool 지도, 4개 모델 백엔드와 **W 그리드 규칙**(asap7 = 0.07µ 핀 / gaa2nm = 0.2µ 스택 정수배), 툴콜 규율(설계상태 passthrough·최대 2콜), 제안 포맷(```json/```spice) |
| `analog-ic-robustness-optimization` | WiCkeD 방법론(FEO/DNO/WCO/WCD/미스매치/고시그마/수율)을 ngspice 로 구현·확장할 때의 설계 지식 |

```sh
cp -r hermes/skills/* ~/.hermes/profiles/strong-arm/skills/semiconductor-eda/
```

## 4) 웹 콘솔 연동 확인

콘솔(:8770) → 비교기/VCO 아무 페이지 → 우하단 🤖 → "입력쌍 W를 두 배로
하고 시뮬해 줘" — 에이전트가 `strongarm_run_sim` 한 번으로 실측을 답하고
↧ 적용 버튼이 뜨면 전체 체인이 정상이다.
