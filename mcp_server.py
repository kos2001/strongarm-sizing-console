#!/usr/bin/env python3
"""
mcp_server.py -- dependency-free MCP stdio server exposing the StrongARM sizing
console to agents (e.g. hermes-agent's api_server). Tools: strongarm_run_sim
(direct ngspice eval), and strongarm_{optimize,pareto,pvt,fullflow} which proxy
to the running console backend at $STRONGARM_API (default :8770).

This is the "method 1" MCP tool wrapper. Register it in Claude Code settings
(see README.md) so that agents in a FUTURE session can call the simulator as a
first-class tool instead of shelling out. Within the current session, agents
call run_sim.py directly via Bash (equivalent interface).

Protocol: JSON-RPC 2.0 over stdio, newline-delimited messages (MCP stdio
transport). Implements initialize / tools/list / tools/call. No third-party
packages required (works on the system python3).
"""
import json
import os
import sys

# make `import run_sim` work regardless of the process cwd (hermes-agent stdio
# MCP subprocesses do not set cwd to this directory)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_sim  # local module

PROTOCOL_VERSION = "2024-11-05"
API_BASE = os.environ.get("STRONGARM_API", "http://127.0.0.1:8770")

_PARAMS_SCHEMA = {
    "type": "object",
    "description": "Sizing + config. Keys: vdd, cload_ff, avt_mv_um, n_mc, "
                   "model ('ptm'|'sky130'), and devices (subset of input/tail/ncc/pcc/pre, "
                   "each {w_um,l_nm,m}).",
}
_TARGETS_SCHEMA = {
    "type": "object",
    "description": "Optional spec limits {decision_time_ps, power_uw, offset_sigma_mv} "
                   "(default P1: 400 ps / 100 µW / 5 mV).",
}

TOOLS = [
    {
        "name": "strongarm_run_sim",
        "description": "Simulate a StrongARM latch comparator in ngspice for a given sizing: "
                       "decision_time_ps, power_uw, functional, and Monte-Carlo offset_sigma_mv.",
        "inputSchema": {"type": "object", "properties": {
            "n_mc": {"type": "integer"}, "vdd": {"type": "number"}, "cload_ff": {"type": "number"},
            "avt_mv_um": {"type": "number"}, "model": {"type": "string"},
            "do_offset": {"type": "boolean", "description": "run the offset Monte-Carlo (default true)"},
            "devices": {"type": "object"},
        }},
    },
    {
        "name": "strongarm_optimize",
        "description": "Autonomously size W/M via log-space Differential Evolution + a GP surrogate, "
                       "minimizing power subject to offset + decision-time + functional constraints. "
                       "Returns the search trajectory, final sizing, and pass/fail verdicts.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA}},
    },
    {
        "name": "strongarm_pareto",
        "description": "Map the power ↔ decision-time trade-off with NSGA-II; returns the "
                       "non-dominated Pareto front of feasible designs.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA}},
    },
    {
        "name": "strongarm_pvt",
        "description": "PVT worst-case sign-off: sweep process (SS/TT/FF) × temperature "
                       "(−40/27/125 °C) × voltage (±10%); returns per-corner metrics and worst case.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA}},
    },
    {
        "name": "strongarm_fullflow",
        "description": "End-to-end flow: DE+GP sizing → Monte-Carlo offset → post-layout parasitic "
                       "re-sim → PVT sign-off, with a per-stage verdict and overall SIGNED-OFF/NOT-CLEAN.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA}},
    },
    {
        "name": "strongarm_wicked",
        "description": "WiCkeD-inspired open flow: FEO/DNO feasibility and sensitivity-guided sizing, "
                       "WCO PVT worst-case operation, and WCD high-sigma/yield proxy.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "dno_iterations": {"type": "integer"}, "wcd_samples": {"type": "integer"}}},
    },
    {
        "name": "strongarm_wicked_importance",
        "description": "High-sigma importance-sampling proxy around the WCD-limiting region, with "
                       "Gaussian likelihood reweighting and full-device mismatch budget.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "n": {"type": "integer"}, "shift_beta": {"type": "number"}}},
    },
    {
        "name": "strongarm_wicked_optimize",
        "description": "Yield-aware WiCkeD-style design-centering coordinate search using WCO/WCD feedback.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "rounds": {"type": "integer"}}},
    },
    {
        "name": "strongarm_wicked_screening",
        "description": "Parameter screening: rank design variables by normalized sensitivity "
                       "to decision-time, power, and offset.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "delta": {"type": "number"}}},
    },
    {
        "name": "strongarm_wicked_yieldsweep",
        "description": "Yield vs global process variation sweep (WiCkeD yield-plot style).",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "n_points": {"type": "integer"}}},
    },
    {
        "name": "strongarm_wicked_yop",
        "description": "YOP-like yield optimization: maximize WCD beta sigma via coordinate search.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "iterations": {"type": "integer"}}},
    },
    {
        "name": "strongarm_wicked_postlayout",
        "description": "Post-layout WCD re-evaluation with layout-extracted parasitics.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA,
            "n_samples": {"type": "integer"}}},
    },
    {
        "name": "strongarm_wicked_corners",
        "description": "Worst-case corner extraction: rank the full 27-corner PVT grid by decision margin.",
        "inputSchema": {"type": "object", "properties": {"params": _PARAMS_SCHEMA, "targets": _TARGETS_SCHEMA}},
    },
    {
        "name": "vco_simulate",
        "description": "Simulate the xcpl ring VCO in ngspice for a given sizing/params "
                       "(devices invp/invn/starvep/starven/xcplp/rstp, vdd, vctrl, n_stages odd, cload_ff). "
                       "Returns f_osc_ghz, power_uw, vpp, oscillates; do_tuning=true adds the V_ctrl tuning curve/Kvco.",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "do_tuning": {"type": "boolean"}}},
    },
    {
        "name": "vco_optimize",
        "description": "Auto-size the ring VCO device widths (DE + GP surrogate, real ngspice) to hit a target "
                       "oscillation frequency at minimum power. targets={f_ghz: X}. Returns trajectory, final_params, tuning.",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "targets": {"type": "object"}}},
    },
    {
        "name": "vco_wicked",
        "description": "WiCkeD-inspired flow for the ring VCO (starved or xcpl topology): FEO feasibility, "
                       "DNO frequency-centering refinement, WCO PVT worst case, WCD sigma/yield proxy, "
                       "per-device mismatch Monte Carlo (start-up/latch-up risk), screening, corners, post-layout.",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "targets": {"type": "object"},
            "dno_iterations": {"type": "integer"}, "wcd_samples": {"type": "integer"}, "mc_samples": {"type": "integer"}}},
    },
    {
        "name": "vco_wicked_mismatch",
        "description": "Ring-VCO per-device Vth mismatch Monte Carlo: sigma_f/f spread and oscillation-failure "
                       "count (xcpl cross-coupled latch-up risk under Pelgrom mismatch).",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "n": {"type": "integer"}}},
    },
    {
        "name": "vco_wicked_screening",
        "description": "Ring-VCO parameter screening: rank device widths by frequency/power sensitivity, "
                       "flagging moves that kill the oscillation.",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "targets": {"type": "object"},
            "delta": {"type": "number"}}},
    },
    {
        "name": "vco_wicked_wcd",
        "description": "Ring-VCO worst-case distance (sigma robustness proxy) over process skew, VDD, and temperature.",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "targets": {"type": "object"},
            "n_samples": {"type": "integer"}}},
    },
    {
        "name": "vco_wicked_corners",
        "description": "Ring-VCO worst-case corner extraction: rank the 27-corner PVT grid by frequency-band margin.",
        "inputSchema": {"type": "object", "properties": {"params": {"type": "object"}, "targets": {"type": "object"}}},
    },
]
_TOOL_ENDPOINT = {
    "strongarm_optimize": "/api/optimize",
    "strongarm_pareto": "/api/pareto",
    "strongarm_pvt": "/api/pvt",
    "strongarm_fullflow": "/api/fullflow",
    "strongarm_wicked": "/api/wicked/fullflow",
    "vco_simulate": "/api/vco/simulate",
    "vco_optimize": "/api/vco/optimize",
    "strongarm_wicked_importance": "/api/wicked/importance",
    "strongarm_wicked_optimize": "/api/wicked/optimize",
    "strongarm_wicked_screening": "/api/wicked/screening",
    "strongarm_wicked_yieldsweep": "/api/wicked/yieldsweep",
    "strongarm_wicked_yop": "/api/wicked/yop",
    "strongarm_wicked_postlayout": "/api/wicked/postlayout",
    "strongarm_wicked_corners": "/api/wicked/corners",
    "vco_wicked": "/api/vco/wicked/fullflow",
    "vco_wicked_mismatch": "/api/vco/wicked/mismatch",
    "vco_wicked_screening": "/api/vco/wicked/screening",
    "vco_wicked_wcd": "/api/vco/wicked/wcd",
    "vco_wicked_corners": "/api/vco/wicked/corners",
}


def _api_post(path, body):
    """Proxy heavier flows to the running console backend (launchd service)."""
    import urllib.request
    req = urllib.request.Request(API_BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.loads(r.read())


def _send(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _result(rid, result):
    _send({"jsonrpc": "2.0", "id": rid, "result": result})


def _error(rid, code, msg):
    _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": msg}})


def handle(msg):
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        _result(rid, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "strongarm-sim", "version": "0.1.0"},
        })
    elif method == "ping":
        _result(rid, {})
    elif method in ("notifications/initialized", "notifications/cancelled"):
        pass  # notifications, no response
    elif method == "tools/list":
        _result(rid, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        try:
            if name == "strongarm_run_sim":
                do_off = args.pop("do_offset", True)
                out = run_sim.run_sim(args, do_offset=do_off)
            elif name in _TOOL_ENDPOINT:
                out = _api_post(_TOOL_ENDPOINT[name], args)   # proxy to the running backend
            else:
                _error(rid, -32602, f"unknown tool {name}")
                return
            _result(rid, {"content": [{"type": "text", "text": json.dumps(out, indent=2)}]})
        except Exception as e:  # surface errors to the caller
            _error(rid, -32000, f"{name} failed: {e}")
    elif rid is not None:
        _error(rid, -32601, f"method not found: {method}")


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        handle(msg)


if __name__ == "__main__":
    main()
