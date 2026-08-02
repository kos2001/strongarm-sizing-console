"""The sign-off flow must cover the terms that dominate, and say what it did not judge.

`fullflow` ran sizing → post-layout → PVT → layout/DRC and called that sign-off,
while omitting the input-referred error terms measured to be first-order: kickback
(above the offset σ), hysteresis (which does not calibrate out), the offset budget
past the input pair, and the common-mode range.

The offset budget stage also catches a defect in the optimizer's objective. Its cost
function prices the input pair's mismatch only, so minimising power it grows the
input pair — the one thing the penalty sees — while shrinking the latch and precharge
pairs, whose mismatch is then free. Measured: input 8.0→19.12 µm, ncc 4.0→1.16 µm,
reported σ improving 1.285→0.889 mV while the real budget went 1.669→3.392 mV. The
reported number improves as the actual offset doubles. Pricing every pair inside the
search needs a per-group referral factor this code does not have, so instead the
winner is measured once and the discrepancy is reported — these tests pin that it is
never silent.
"""
import pytest

import run_sim
import server

TARGETS = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}


# ── the optimizer must confess when its offset term is optimistic ────────────

@pytest.fixture(scope="module")
def opt():
    return server.optimize(run_sim._full({"model": "ptm45"}), TARGETS)


def test_optimizer_measures_the_full_budget_of_its_winner(opt):
    b = opt["offset_budget"]
    assert b is not None
    assert b["total_sigma_mv"] is not None
    assert set(b["per_device"]) == set(run_sim.OFFSET_PAIRS)


def test_optimizer_flags_which_device_dominates_the_offset(opt):
    """The warning's job changed once the cost function started pricing every pair: it
    is no longer evidence of a modelling gap but a pointer to the binding device. It
    must name that device and send the reader to the measured total."""
    b = opt["offset_budget"]
    ratio = b["total_sigma_mv"] / b["input_only_sigma_mv"]
    if ratio > 1.25:
        w = opt["offset_budget_warning"]
        assert w, (ratio, b)
        assert b["dominant"][0] in w
        assert "total_sigma_mv" in w
        # and it must not still claim the objective ignores latch mismatch
        assert "does not price" not in w
    else:
        assert opt["offset_budget_warning"] is None


def test_the_warning_names_which_measurement_it_compares():
    """The budget re-measures the input pair with its own n_mc, so the number in the
    warning differs slightly from the result's `offset` field. It has to say so or it
    reads as a contradiction."""
    r = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS, budget_n_mc=6)
    if r["offset_budget_warning"]:
        assert "n_mc=6" in r["offset_budget_warning"]


def test_the_budget_check_is_skippable(opt):
    r = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS, budget_check=False)
    assert r["offset_budget"] is None
    assert r["offset_budget_warning"] is None


def test_the_optimizer_really_does_shrink_the_latch():
    """The mechanism behind the warning, asserted directly rather than trusted."""
    seed = run_sim._full({"model": "ptm45"})
    fin = server.optimize(seed, TARGETS, budget_check=False)["final_params"]
    assert fin["devices"]["input"]["w_um"] > seed["devices"]["input"]["w_um"]
    shrunk = [g for g in ("ncc", "pcc", "pre", "prei")
              if fin["devices"][g]["w_um"] < seed["devices"][g]["w_um"]]
    assert shrunk, {g: fin["devices"][g]["w_um"] for g in ("ncc", "pcc", "pre", "prei")}
    # and that shrinking raises those groups' mismatch sigma
    for g in shrunk:
        assert run_sim.pelgrom_sigma_v(fin, g) > run_sim.pelgrom_sigma_v(seed, g)


# ── the flow must be complete, and honest about what it judged ──────────────

@pytest.fixture(scope="module")
def flow():
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/fullflow",
            data=json.dumps({"params": {"model": "ptm45"}}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            return json.load(r)
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def test_flow_covers_the_first_order_error_terms(flow):
    names = " | ".join(s["name"] for s in flow["stages"])
    for expected in ("Offset budget", "Kickback", "Hysteresis", "Common-mode range"):
        assert expected in names, (expected, names)


def test_flow_keeps_the_original_stages(flow):
    names = " | ".join(s["name"] for s in flow["stages"])
    for expected in ("Sizing", "Post-layout", "PVT", "Layout + DRC"):
        assert expected in names, (expected, names)


def test_unjudged_stages_do_not_fail_the_flow(flow):
    """A stage with no target is measured but not judged. Counting that as a failure
    would make every flow fail the moment a spec is merely reported."""
    unjudged = [s for s in flow["stages"] if s["ok"] is None]
    assert unjudged, "expected kickback to be reported-only without a target"
    assert flow["reported_not_judged"] == [s["name"] for s in unjudged]
    judged = [s["ok"] for s in flow["stages"] if s["ok"] is not None]
    assert flow["overall"] == all(judged)


def test_overall_cannot_be_mistaken_for_everything_passed(flow):
    """If anything went unjudged, the flow has to name it next to the verdict."""
    if flow["overall"] is True:
        assert "reported_not_judged" in flow


def test_hysteresis_is_measured_at_the_designs_own_max_fclk(flow):
    """An arbitrary clock period would measure memory the circuit never sees."""
    hy, mf = flow["hysteresis"], flow["max_fclk"]
    assert mf.get("max_fclk_ghz")
    assert hy.get("clk_period_ns") == pytest.approx(1.0 / mf["max_fclk_ghz"], rel=1e-3)


def test_kickback_reports_the_driver_it_assumed(flow):
    kb = flow["kickback"]
    assert kb.get("rs_ohm") and kb.get("cs_ff")
    detail = next(s["detail"] for s in flow["stages"] if "Kickback" in s["name"])
    assert "Rs" in detail and "Cs" in detail


def test_kickback_is_judged_when_a_target_exists():
    import json
    import threading
    import urllib.request
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        body = {"params": {"model": "ptm45"},
                "targets": {**TARGETS, "noise_uv_rms": 250, "kickback_diff_mv": 10}}
        req = urllib.request.Request(
            f"http://127.0.0.1:{httpd.server_address[1]}/api/fullflow",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=1800) as r:
            d = json.load(r)
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)
    kb_stage = next(s for s in d["stages"] if "Kickback" in s["name"])
    assert kb_stage["ok"] is not None
    assert "vs target 10" in kb_stage["detail"]
    assert "Kickback (input disturbance)" not in d["reported_not_judged"]
