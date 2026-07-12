#!/bin/sh
# strongarm MCP 서버를 현재 활성 hermes 프로파일에 등록하고 스킬을 설치한다.
# 사용: ./hermes/register.sh [profile]   (profile 생략 시 활성 프로파일)
set -e
cd "$(dirname "$0")/.."
REPO="$(pwd)"
PROFILE="${1:-}"

if [ -n "$PROFILE" ]; then
    hermes profile use "$PROFILE"
fi

echo "Y" | hermes mcp add strongarm --command python3 --args "$REPO/mcp_server.py" || true
hermes mcp test strongarm

ACTIVE="$(hermes profile current 2>/dev/null || echo "${PROFILE:-default}")"
SKILL_DIR="$HOME/.hermes/profiles/$ACTIVE/skills/semiconductor-eda"
mkdir -p "$SKILL_DIR"
cp -r "$REPO/hermes/skills/"* "$SKILL_DIR/"
echo "registered MCP 'strongarm' + skills into profile '$ACTIVE'"
