#!/bin/zsh
# Re-measure the cost table in SKILL.md on this machine.
#
# Each endpoint runs in its own fresh server so "cold" means an empty deck memo
# cache — measuring them all against one server would let an earlier case warm a
# later one's decks and understate the cost (pvt warms wicked_corners, for
# example). "warm" is the identical call repeated against the same server.
#
# Usage: ./measure_tool_cost.sh [repo_root]
#
# The repo root is taken from the argument, else $STRONGARM_REPO, else guessed.
# Guessing has to cope with two layouts: in-repo (hermes/skills/<skill>/scripts)
# and installed into a hermes profile (profiles/<p>/skills/<cat>/<skill>/scripts),
# where walking up lands in the profile rather than the repo.
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO=""
for c in "$1" "$STRONGARM_REPO" "$HERE/../../../.." "$HERE/../../../../.." \
         "$HOME/gitspace/ip-dev-fde/strongarm_sim"; do
  [ -n "$c" ] && [ -f "$c/webapp/server.py" ] && { REPO="$(cd "$c" && pwd)"; break }
done
if [ -z "$REPO" ]; then
  echo "cannot find the strongarm repo — pass it: $0 /path/to/strongarm_sim" >&2
  echo "(or set STRONGARM_REPO)" >&2
  exit 1
fi
echo "repo: $REPO"
T='{"decision_time_ps":400,"power_uw":150,"offset_sigma_mv":5}'
PORT=8810

run() {   # run <label> <path> <json body>
  PORT=$((PORT+1))
  (cd "$REPO/webapp" && python3 server.py $PORT > /tmp/cost_$PORT.log 2>&1 &)
  sleep 3
  local cold warm
  cold=$(curl -s -m 3600 -o /tmp/cost_body.json -w '%{time_total}' \
      -X POST "http://127.0.0.1:$PORT$2" -H 'Content-Type: application/json' -d "$3")
  warm=$(curl -s -m 3600 -o /dev/null -w '%{time_total}' \
      -X POST "http://127.0.0.1:$PORT$2" -H 'Content-Type: application/json' -d "$3")
  printf '%-28s cold=%8ss  warm=%8ss\n' "$1" "$cold" "$warm"
  pkill -f "server.py $PORT" 2>/dev/null || true
}

echo "== per-endpoint (ptm45 default) =="
run "layout (no SPICE)"      /api/layout         '{"params":{}}'
run "run_sim (no offset)"    /api/simulate       '{"params":{},"do_offset":false}'
run "run_sim (+offset MC)"   /api/simulate       '{"params":{},"do_offset":true}'
run "maxfclk"                /api/maxfclk        '{"params":{}}'
run "sensitivity"            /api/sensitivity    "{\"params\":{},\"targets\":$T}"
run "metastability"          /api/metastability  '{"params":{}}'
run "yield (n=24)"           /api/yield          "{\"params\":{},\"targets\":$T,\"n\":24}"
run "pvt (45 corners)"       /api/pvt            '{"params":{}}'
run "wicked_corners"         /api/wicked/corners "{\"params\":{},\"targets\":$T}"
run "wicked_wcd"             /api/wicked/wcd     "{\"params\":{},\"targets\":$T,\"n_samples\":12}"
run "pareto"                 /api/pareto         "{\"params\":{},\"targets\":$T}"
run "optimize"               /api/optimize       "{\"params\":{},\"targets\":$T}"
run "fullflow"               /api/fullflow       "{\"params\":{},\"targets\":$T}"
run "vco_simulate"           /api/vco/simulate   '{"params":{}}'
run "vco_tuning"             /api/vco/tuning     '{"params":{}}'
run "vco_pvt"                /api/vco/pvt        '{"params":{}}'
run "vco_pareto"             /api/vco/pareto     '{"params":{}}'
run "vco_optimize"           /api/vco/optimize   '{"params":{},"targets":{"f_ghz":3.0}}'

echo
echo "== backend multiplier (run_sim / pvt / optimize) =="
for spec in 'ptm45|{"model":"ptm45"}' 'sky130|{"model":"sky130","vdd":1.8}' \
            'asap7|{"model":"asap7"}' 'gaa2nm|{"model":"gaa2nm"}'; do
  m=${spec%%|*}; p=${spec#*|}; PORT=$((PORT+1))
  (cd "$REPO/webapp" && python3 server.py $PORT > /tmp/cost_$PORT.log 2>&1 &)
  sleep 3
  s=$(curl -s -m 900  -o /dev/null -w '%{time_total}' -X POST "http://127.0.0.1:$PORT/api/simulate" \
        -H 'Content-Type: application/json' -d "{\"params\":$p,\"do_offset\":false}")
  v=$(curl -s -m 1800 -o /dev/null -w '%{time_total}' -X POST "http://127.0.0.1:$PORT/api/pvt" \
        -H 'Content-Type: application/json' -d "{\"params\":$p}")
  o=$(curl -s -m 3600 -o /dev/null -w '%{time_total}' -X POST "http://127.0.0.1:$PORT/api/optimize" \
        -H 'Content-Type: application/json' -d "{\"params\":$p,\"targets\":$T}")
  printf '%-8s run_sim=%8ss  pvt45=%8ss  optimize=%9ss\n' "$m" "$s" "$v" "$o"
  pkill -f "server.py $PORT" 2>/dev/null || true
done
