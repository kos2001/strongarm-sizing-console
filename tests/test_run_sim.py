"""Regression tests for the SPICE backend (run_sim.py)."""
import run_sim


def test_seed_is_functional():
    r = run_sim.run_sim({}, do_offset=False)
    nom = r["nominal"]
    assert nom["functional"] is True
    assert nom["decision_time_ps"] is not None and nom["decision_time_ps"] > 0
    assert nom["power_uw"] is not None and nom["power_uw"] > 0


def test_nominal_keys_present():
    nom = run_sim.measure_nominal(run_sim.DEFAULT_PARAMS)
    for k in ("decision_time_ps", "power_uw", "final_diff_v", "functional", "noise_uv_rms"):
        assert k in nom


def test_noise_only_when_requested():
    assert run_sim.measure_nominal(run_sim.DEFAULT_PARAMS, with_noise=False)["noise_uv_rms"] is None
    nz = run_sim.measure_nominal(run_sim.DEFAULT_PARAMS, with_noise=True)["noise_uv_rms"]
    assert nz is not None and 0 < nz < 5000   # sane µVrms range


def test_offset_positive():
    r = run_sim.run_sim({}, do_offset=True, seed=7)
    off = r["offset"]
    assert off["offset_sigma_mv"] >= 0
    assert off["pelgrom_sigma_vth_mv"] > 0
    assert off["n_mc"] == run_sim.DEFAULT_PARAMS["n_mc"]


def test_wider_input_lowers_offset():
    """Pelgrom: larger input-pair area -> smaller offset sigma."""
    base = run_sim.run_sim({}, do_offset=True, seed=3)["offset"]["offset_sigma_mv"]
    wide = run_sim.run_sim({"devices": {"input": {"w_um": 32.0, "l_nm": 80.0, "m": 4}}},
                           do_offset=True, seed=3)["offset"]["offset_sigma_mv"]
    assert wide < base


def test_parasitics_slow_decision():
    fast = run_sim.run_sim({"parasitic": False}, do_offset=False)["nominal"]["decision_time_ps"]
    slow = run_sim.run_sim({"parasitic": True}, do_offset=False)["nominal"]["decision_time_ps"]
    assert slow >= fast


def test_partial_device_merge():
    """A partial device dict must keep the missing fields from the default
    (field-wise merge) rather than dropping them and crashing gen_netlist."""
    merged = run_sim.merge_devices({"input": {"w_um": 10}})
    assert merged["input"] == {"w_um": 10, "l_nm": 80.0, "m": 4}
    r = run_sim.run_sim({"devices": {"input": {"w_um": 10}}}, do_offset=False)
    assert r["nominal"]["functional"] is True


def test_gen_netlist_defaults_unchanged():
    """Clock parameterization must be byte-identical to the original when the
    optional timing params are absent (protects existing behavior/tests)."""
    nl = run_sim.gen_netlist(run_sim.DEFAULT_PARAMS, vdiff=0.01)
    assert "PULSE(0 0.7 200p 12p 12p 3.0n 6.0n)" in nl   # 기본 vdd 0.7
    assert "tran 1.0p 2.2n" in nl   # 1 ps step (perf): decision time bit-identical to 0.2 ps


def test_max_fclk_sweep():
    r = run_sim.max_fclk_sweep({})
    assert r["max_fclk_ghz"] is not None and r["max_fclk_ghz"] > 0
    assert r["energy_fj_at_max"] is not None and r["energy_fj_at_max"] > 0
    # a short enough period must eventually fail to resolve
    assert any(not p["ok"] for p in r["points"])
    # every "ok" period both resolves and resets
    assert all(p["functional"] and p["reset_ok"] for p in r["points"] if p["ok"])


def test_metastability_tau_and_monotonic():
    m = run_sim.metastability_sweep({})
    assert m["tau_ps"] is not None and m["tau_ps"] > 0
    resolved = [p for p in m["points"] if p["resolved"]]
    assert len(resolved) >= 3
    # decision time must fall as input grows (regeneration regime)
    resolved.sort(key=lambda p: p["vin_v"])
    assert resolved[0]["decision_time_ps"] > resolved[-1]["decision_time_ps"]
