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
    run_sim._ng_stats.update(hits=0, misses=0, shared=0)
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


def test_concurrent_identical_decks_share_one_process(monkeypatch):
    from concurrent.futures import Future, ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from unittest.mock import Mock
    ready = Barrier(8)
    class WaitingFuture(Future):
        def result(self, timeout=None):
            ready.wait(timeout=5)
            return super().result(timeout=5)
    def process(*args, **kwargs):
        ready.wait(timeout=5)
        return SimpleNamespace(stdout='value = 42', stderr='', returncode=0)
    run = Mock(side_effect=process)
    monkeypatch.setattr(run_sim, 'Future', WaitingFuture)
    monkeypatch.setattr(run_sim.subprocess, 'run', run)
    with ThreadPoolExecutor(max_workers=8) as pool:
        values = list(pool.map(lambda _: run_sim._run('deterministic deck'), range(8)))
    assert values == ['value = 42\n'] * 8
    assert run.call_count == 1
    assert run_sim.ngspice_cache_stats()['in_flight'] == 0


def test_shared_exception_releases_followers_and_allows_retry(monkeypatch):
    from concurrent.futures import Future, ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from unittest.mock import Mock
    ready = Barrier(2)
    class WaitingFuture(Future):
        def result(self, timeout=None):
            ready.wait(timeout=5)
            return super().result(timeout=5)
    def failed(*args, **kwargs):
        ready.wait(timeout=5)
        raise TimeoutError('simulator timeout')
    monkeypatch.setattr(run_sim, 'Future', WaitingFuture)
    monkeypatch.setattr(run_sim.subprocess, 'run', failed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        requests = [pool.submit(run_sim._run, 'retry deck') for _ in range(2)]
        for request in requests:
            with pytest.raises(TimeoutError, match='simulator timeout'):
                request.result(timeout=5)
    assert run_sim.ngspice_cache_stats()['in_flight'] == 0
    assert not run_sim._ng_cache
    run = Mock(return_value=SimpleNamespace(stdout='recovered', stderr='', returncode=0))
    monkeypatch.setattr(run_sim.subprocess, 'run', run)
    assert run_sim._run('retry deck') == 'recovered\n'
    assert run.call_count == 1


def test_failed_process_is_not_cached(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    run = Mock(return_value=SimpleNamespace(stdout='', stderr='model missing', returncode=1))
    monkeypatch.setattr(run_sim.subprocess, 'run', run)
    assert run_sim._run('missing model') == run_sim._run('missing model')
    assert run.call_count == 2
    assert not run_sim._ng_cache


@pytest.mark.parametrize('decks,cache', [
    (['deck A', 'deck B'], True),
    (['deck A', 'deck A'], False),
    (['WRDATA wave.txt v(out)', 'WRDATA wave.txt v(out)'], True),
])
def test_independent_or_file_writing_requests_do_not_share(monkeypatch, decks, cache):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace
    from unittest.mock import Mock
    ready = Barrier(2)
    def process(*args, **kwargs):
        ready.wait(timeout=5)
        return SimpleNamespace(stdout='done', stderr='', returncode=0)
    run = Mock(side_effect=process)
    monkeypatch.setattr(run_sim.subprocess, 'run', run)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(lambda deck: run_sim._run(deck, cache=cache), decks)) == ['done\n'] * 2
    assert run.call_count == 2
