"""Guards the deck memo cache and the parallel-map helper in run_sim.

The cache is only safe because an ngspice deck's stdout is a pure function of the
deck text. These tests pin the two ways that could stop being true: a deck that
also writes a file (waveform capture) must never be served from cache, and
turning the cache off must not change a single number.
"""
import random

import pytest

import run_sim


@pytest.fixture(autouse=True)
def _clean_cache():
    run_sim._ng_cache.clear()
    del run_sim._ng_order[:]
    run_sim._ng_stats.update(hits=0, misses=0)
    yield


def test_identical_deck_is_served_from_cache():
    p = run_sim._full({})
    deck = run_sim.gen_netlist(p, vdiff=0.01)
    first = run_sim._run(deck)
    second = run_sim._run(deck)
    assert second == first
    assert run_sim.ngspice_cache_stats()["hits"] == 1
    assert run_sim.ngspice_cache_stats()["misses"] == 1


def test_different_decks_do_not_collide():
    p = run_sim._full({})
    a = run_sim._run(run_sim.gen_netlist(p, vdiff=0.01))
    b = run_sim._run(run_sim.gen_netlist(p, vdiff=0.05))
    assert run_sim._parse(a, "fdiff") != run_sim._parse(b, "fdiff")
    assert run_sim.ngspice_cache_stats()["hits"] == 0


def test_file_writing_decks_bypass_the_cache():
    """capture_waveform's deck has a side effect beyond stdout — a cache hit
    would return the measurements but leave no waveform file behind."""
    p = run_sim._full({})
    for _ in range(2):
        w = run_sim.capture_waveform(p)
        assert w.get("n", 0) > 0, w
    assert run_sim.ngspice_cache_stats()["hits"] == 0


def test_cache_disabled_gives_the_same_answers():
    p = run_sim._full({})
    with_cache = run_sim.metastability_sweep(p)
    run_sim._ng_cache.clear()
    del run_sim._ng_order[:]
    saved, run_sim._NG_CACHE_MAX = run_sim._NG_CACHE_MAX, 0
    try:
        without = run_sim.metastability_sweep(p)
    finally:
        run_sim._NG_CACHE_MAX = saved
    assert without == with_cache


def test_cache_evicts_to_its_bound():
    p = run_sim._full({})
    saved, run_sim._NG_CACHE_MAX = run_sim._NG_CACHE_MAX, 2
    try:
        for i in range(4):
            run_sim._run(run_sim.gen_netlist(p, vdiff=0.01 + 0.005 * i))
        assert len(run_sim._ng_cache) == 2
        assert len(run_sim._ng_order) == 2
    finally:
        run_sim._NG_CACHE_MAX = saved


def test_pmap_preserves_order():
    assert run_sim.pmap(lambda x: x * x, range(12)) == [x * x for x in range(12)]
    assert run_sim.pmap(lambda x: x, []) == []
    assert run_sim.pmap(lambda x: x, [5]) == [5]


def test_pmap_propagates_exceptions():
    def boom(x):
        if x == 3:
            raise ValueError("boom")
        return x

    with pytest.raises(ValueError):
        run_sim.pmap(boom, range(6))


def test_sweeps_stay_correct_under_parallel_map():
    """metastability_sweep now fans out; the tau fit still has to come back in
    amplitude order or the regression fit is meaningless."""
    p = run_sim._full({})
    r = run_sim.metastability_sweep(p)
    amps = [pt["vin_v"] for pt in r["points"]]
    assert amps == sorted(amps)
    assert r["tau_ps"] is not None and r["tau_ps"] > 0


def test_offset_mc_is_reproducible_across_runs():
    p = run_sim._full({"n_mc": 8})
    a = run_sim.measure_offset(p, random.Random(4))
    b = run_sim.measure_offset(p, random.Random(4))
    assert a["samples_mv"] == b["samples_mv"]
