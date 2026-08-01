"""Does sizing need all 45 corners, or only a worst case?

The optimizer sizes against ONE assumed corner (slow-N / -40 °C / 0.9·VDD) and
signs off on 45. These tests pin the measured answer, because it is two-sided and
easy to over-claim:

* **Functionality** — the assumed corner is sufficient. Across sampled sizings no
  design passed it and then failed another corner, and dropping the guard leaves
  real corner failures behind.
* **Timing** — it is NOT sufficient. The slowest corner wanders (16 distinct
  corners across 24 random sizings, never the assumed one), so a subset
  under-estimates worst-case delay and timing closure needs the full sweep.

Kept small enough to run in CI; the wider 24-sizing sweep that produced the
numbers in `corner_guarantee` is documented in the README.
"""
import random

import pytest

import run_sim
import server

SK = 0.05
ASSUMED = ("SS/-40/0.9", SK, SK, -40, 0.9)
DEV = ("input", "tail", "ncc", "pcc", "pre", "prei")
TARGETS = {"decision_time_ps": 400, "power_uw": 150, "offset_sigma_mv": 5}


def _corners():
    out = []
    for proc, ns, ps in (("SS", SK, SK), ("TT", 0, 0), ("FF", -SK, -SK),
                         ("SF", SK, -SK), ("FS", -SK, SK)):
        for t in (-40, 27, 125):
            for vf in (0.9, 1.0, 1.1):
                out.append((f"{proc}/{t:+d}/{vf}", ns, ps, t, vf))
    return out


def _sweep(p, corners):
    def one(c):
        lbl, ns, ps, t, vf = c
        n = run_sim.run_sim({**p, "vdd": round(p["vdd"] * vf, 4), "temp": t,
                             "nskew": ns, "pskew_p": ps}, do_offset=False)["nominal"]
        tdec = n.get("decision_time_ps")
        return (lbl, tdec, bool(n.get("functional")) and tdec is not None)
    return run_sim.pmap(one, corners)


@pytest.fixture(scope="module")
def sweeps():
    """A handful of deliberately different sizings, each over all 45 corners."""
    rng = random.Random(11)
    sizings = [{}, {"input": {"w_um": 24.0}}, {"tail": {"w_um": 30.0, "m": 8}}]
    sizings += [{k: {"w_um": round(10 ** rng.uniform(-0.1, 1.4), 2)} for k in DEV}
                for _ in range(5)]
    corners = _corners()
    return [_sweep(run_sim._full({"model": "ptm45", "devices": d}), corners) for d in sizings]


def test_the_assumed_corner_bounds_functionality(sweeps):
    """No sizing may pass the assumed corner and fail a different one — that is
    exactly what would make single-corner sizing unsafe."""
    escapes = []
    for res in sweeps:
        ok = {lbl: f for lbl, _, f in res}
        if ok.get(ASSUMED[0]) and not all(ok.values()):
            escapes.append([l for l, f in ok.items() if not f])
    assert escapes == [], f"passed {ASSUMED[0]} yet failed: {escapes}"


def test_failing_corner_sets_are_nested(sweeps):
    """Nestedness is why one corner can stand in for the rest on functionality."""
    sets = [frozenset(l for l, _, f in res if not f) for res in sweeps]
    for a in sets:
        for b in sets:
            assert a <= b or b <= a, f"not nested: {sorted(a ^ b)}"


def test_the_assumed_corner_does_not_bound_timing(sweeps):
    """The slowest corner is rarely the assumed one, so its delay is not a
    worst-case delay. If this ever starts passing, the corner set changed and the
    guarantee wording in `corner_guarantee` needs revisiting."""
    hits = 0
    for res in sweeps:
        func = [(l, t) for l, t, f in res if f]
        if not func:
            continue
        if max(func, key=lambda x: x[1])[0] == ASSUMED[0]:
            hits += 1
    assert hits < len(sweeps), "assumed corner was the slowest everywhere — unexpected"


def test_a_small_corner_subset_underestimates_worst_delay(sweeps):
    """Concretely: the three most frequent worst corners still miss the true
    worst delay by a wide margin, which is why sign-off runs all 45."""
    import collections
    counter = collections.Counter()
    rows = []
    for res in sweeps:
        func = {l: t for l, t, f in res if f}
        if not func:
            continue
        counter[max(func, key=func.get)] += 1
        rows.append(func)
    subset = {c for c, _ in counter.most_common(3)}
    worst_gap = 0.0
    for r in rows:
        true_worst = max(r.values())
        have = [r[c] for c in subset if c in r]
        est = max(have) if have else 0.0
        worst_gap = max(worst_gap, (true_worst - est) / true_worst)
    assert worst_gap > 0.1, f"a 3-corner subset was unexpectedly tight ({worst_gap:.1%})"


def test_the_corner_guard_earns_its_cost():
    """Sizing with the guard must survive all 45 corners; sizing without it must
    not. This is the end-to-end justification for corner_aware defaulting on."""
    corners = _corners()
    guarded = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS, corner_aware=True)
    naive = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS, corner_aware=False)
    g_bad = [l for l, _, f in _sweep(guarded["final_params"], corners) if not f]
    n_bad = [l for l, _, f in _sweep(naive["final_params"], corners) if not f]
    assert g_bad == [], f"guarded sizing still failed: {g_bad}"
    assert len(n_bad) > 0, "nominal-only sizing passed all corners — guard looks unnecessary"


def test_optimize_states_the_boundary_of_its_corner_claim():
    r = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS, corner_aware=True)
    g = r["corner_guarantee"]
    assert "FUNCTIONALITY" in g and "45-corner" in g
    off = server.optimize(run_sim._full({"model": "ptm45"}), TARGETS, corner_aware=False)
    assert "no corner guard" in off["corner_guarantee"]
