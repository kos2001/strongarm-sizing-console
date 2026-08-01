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
PROFILE_DIR="$HOME/.hermes/profiles/$ACTIVE"
SKILL_DIR="$PROFILE_DIR/skills/semiconductor-eda"
mkdir -p "$SKILL_DIR"
cp -r "$REPO/hermes/skills/"* "$SKILL_DIR/"

# SOUL.md (the agent's system prompt) lives in the repo so it is reviewed and
# versioned with the tools it describes — the profile copy is a deployment
# artifact. Any hand-edit there is backed up rather than silently overwritten.
if [ -f "$REPO/hermes/SOUL.md" ]; then
    if [ -f "$PROFILE_DIR/SOUL.md" ] && ! cmp -s "$REPO/hermes/SOUL.md" "$PROFILE_DIR/SOUL.md"; then
        cp "$PROFILE_DIR/SOUL.md" "$PROFILE_DIR/SOUL.md.bak-$(date +%Y%m%d-%H%M%S)"
        echo "  (previous SOUL.md backed up)"
    fi
    cp "$REPO/hermes/SOUL.md" "$PROFILE_DIR/SOUL.md"
fi

echo "registered MCP 'strongarm' + skills + SOUL.md into profile '$ACTIVE'"
echo "restart the gateway to pick them up:"
echo "  launchctl kickstart -k gui/\$UID/ai.hermes.gateway-$ACTIVE"
