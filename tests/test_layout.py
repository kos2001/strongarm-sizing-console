"""Regression tests for layout synthesis + parasitic extraction (layout.py)."""
import layout
import run_sim


def test_generate_layout_area_and_drc():
    r = layout.generate_layout(run_sim.DEFAULT_PARAMS)
    assert r["area_um2"] > 0
    assert r["bbox"]["w"] > 0 and r["bbox"]["h"] > 0
    assert r["drc"]["clean"] is True
    assert r["drc"]["n_violations"] == 0


def test_extract_parasitics_positive():
    pc = layout.extract_parasitics(run_sim.DEFAULT_PARAMS)
    assert pc["c_out_ff"] > 0 and pc["c_int_ff"] > 0
    assert set(pc["per_device_ff"]) == set(run_sim.DEFAULT_PARAMS["devices"])


def test_bigger_devices_more_cap():
    small = layout.extract_parasitics(run_sim.DEFAULT_PARAMS)["c_out_ff"]
    big = layout.extract_parasitics({"devices": {**run_sim.DEFAULT_PARAMS["devices"],
                                                 "pcc": {"w_um": 30.0, "l_nm": 45.0, "m": 8}}})["c_out_ff"]
    assert big > small
