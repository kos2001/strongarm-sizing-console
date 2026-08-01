#!/usr/bin/env python3
"""Verification script for WiCkeD-inspired analog robustness flows.

Run this after modifying wicked.py or its integration points to confirm
all functions, API wiring, and MCP tool registration are intact.

Usage:
    python3 scripts/verify-wicked-flow.py [--root /path/to/strongarm_sim]

Exit code 0 = all checks passed. Non-zero = failure.
"""
import argparse
import json
import os
import py_compile
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    args = ap.parse_args()
    root = os.path.abspath(args.root)
    sys.path.insert(0, root)
    sys.path.insert(0, os.path.join(root, "webapp"))

    # 1) Compile all changed files
    files = ["wicked.py", "webapp/server.py", "mcp_server.py", "tests/test_wicked.py"]
    for rel in files:
        py_compile.compile(os.path.join(root, rel), doraise=True)

    import wicked
    import mcp_server

    # 2) Core function smoke tests
    t = {"decision_time_ps": 900, "power_uw": 2000, "offset_sigma_mv": 20, "yield_pct": 80}

    mb = wicked.mismatch_budget({})
    assert mb["total_sigma_mv"] > 0 and mb["dominant"]["device"] == "input"

    wcd = wicked.worst_case_distance({}, t, n_samples=2, seed=5)
    assert wcd["beta_sigma"] > 0 and 0 <= wcd["estimated_yield_pct"] <= 100

    imp = wicked.importance_sampling_yield({}, t, n=2, seed=13)
    assert imp["n"] == 2 and 0 <= imp["estimated_yield_pct"] <= 100

    scr = wicked.parameter_screening({}, t, delta=0.10)
    for m in ("decision_time_ps", "power_uw", "offset_sigma_mv"):
        assert len(scr["rankings"][m]) == len(wicked.DEV_KEYS)
        assert scr["rankings"][m][0]["sensitivity"] >= scr["rankings"][m][-1]["sensitivity"]

    wcc = wicked.worst_case_corners({}, t)
    assert wcc["total_corners"] == 27 and len(wcc["worst_5"]) == 5

    ys = wicked.yield_sweep({}, t, n_points=2, seed=3)
    assert len(ys["points"]) == 2 and all(0 <= p["yield_pct"] <= 100 for p in ys["points"])

    yop = wicked.yop_optimize({}, t, iterations=1, seed=7)
    assert yop["final_beta_sigma"] > 0

    plw = wicked.postlayout_wcd({}, t, n_samples=2, seed=5)
    assert plw["pre_layout"]["wcd"]["beta_sigma"] > 0 and "par_caps" in plw

    flow = wicked.wicked_flow({}, t, dno_iterations=1, wcd_samples=2, importance_samples=2, seed=4)
    sn = [s["name"] for s in flow["stages"]]
    for name in ["Parameter screening", "Worst-case corner extraction", "Post-layout WCD re-evaluation"]:
        assert name in sn, f"missing stage: {name}"

    # 3) API endpoint wiring
    with open(os.path.join(root, "webapp/server.py"), encoding="utf-8") as f:
        srv = f.read()
    for ep in ["/api/wicked/screening", "/api/wicked/yieldsweep", "/api/wicked/yop",
               "/api/wicked/postlayout", "/api/wicked/corners", "/api/wicked/fullflow",
               "/api/wicked/mismatch", "/api/wicked/importance", "/api/wicked/optimize",
               "/api/wicked/dno", "/api/wicked/wcd"]:
        assert ep in srv, f"missing endpoint: {ep}"

    # 4) MCP tool registration
    for tool in ["strongarm_wicked", "strongarm_wicked_importance", "strongarm_wicked_optimize",
                 "strongarm_wicked_screening", "strongarm_wicked_yieldsweep",
                 "strongarm_wicked_yop", "strongarm_wicked_postlayout",
                 "strongarm_wicked_corners"]:
        assert any(x["name"] == tool for x in mcp_server.TOOLS), f"missing MCP tool: {tool}"
        assert tool in mcp_server._TOOL_ENDPOINT, f"missing endpoint mapping: {tool}"

    print(json.dumps({
        "status": "pass",
        "compiled_files": files,
        "flow_stages": len(flow["stages"]),
        "mcp_tools": 8,
        "api_endpoints": 11,
        "mismatch_sigma_mv": mb["total_sigma_mv"],
        "wcd_beta": wcd["beta_sigma"],
        "yop_beta": yop["final_beta_sigma"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
