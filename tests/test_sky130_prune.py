"""Guards the sky130 deck prune (run_sim._sky130_prune_corner_file).

A sky130 corner deck pulls ~30 model banks; we instantiate only the 1.8 V core
nfet/pfet, so the rest is parse time for models the netlist never references —
93% of a warm sky130 sim before the prune. Dropping them must not move a single
measured number, which is what these tests pin. Skipped when the PDK is absent.
"""
import os
import re
import subprocess
import sys

import pytest

import run_sim

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

pytestmark = pytest.mark.skipif(
    not os.path.exists(run_sim._sky130_lib_path()),
    reason="sky130 PDK not installed (set SKY130_NGSPICE_LIB)")

KEYS = ("tdec", "fdiff", "iavg")


def _measure(corner, prune):
    """Run one sky130 transient in a fresh process (the corner lib is cached
    per-process by path, and the prune setting changes that path) and return the
    raw ngspice measurements."""
    code = (
        "import sys, json; sys.path.insert(0, %r)\n"
        "import run_sim\n"
        "p = run_sim._full({'model': 'sky130', 'vdd': 1.8, 'corner': %r})\n"
        "out = run_sim._run(run_sim.gen_netlist(p, vdiff=0.01))\n"
        "print(json.dumps({k: run_sim._parse(out, k) for k in %r}))\n"
    ) % (ROOT, corner, KEYS)
    env = dict(os.environ)
    env["SKY130_PRUNE"] = "1" if prune else "0"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, env=env, cwd=ROOT, timeout=600)
    assert r.returncode == 0, r.stderr[-2000:]
    import json
    return json.loads(r.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("corner", ["tt", "ss", "ff", "sf", "fs"])
def test_prune_is_bit_identical(corner):
    """Pruned and full decks must agree exactly — not approximately."""
    full, lean = _measure(corner, prune=False), _measure(corner, prune=True)
    assert all(v is not None for v in full.values()), f"full deck gave {full}"
    assert lean == full


def test_prune_actually_drops_banks():
    """The lib we hand ngspice must reference only the kept device families —
    a PDK rename that made the whitelist match nothing would leave the deck
    correct but slow, and this is what catches that."""
    def _is_corner_deck(path):
        base = os.path.basename(path)
        return base.startswith("corner_") or os.path.basename(os.path.dirname(path)) == "corners"

    # Walk only the levels the prune governs: the one-corner lib and the corner
    # deck it points at. Deeper includes (all.spice and its parasitic banks) are
    # kept wholesale on purpose — the subckts read their params.
    incs, seen, stack = [], set(), [run_sim.sky130_corner_lib("tt")]
    while stack:
        path = stack.pop()
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        with open(path) as f:
            for ln in f:
                m = re.match(r'^\s*\.include\s+"([^"]+)"', ln)
                if m:
                    incs.append(os.path.basename(m.group(1)))
                    if _is_corner_deck(m.group(1)):
                        stack.append(m.group(1))
    banks = [b for b in incs if b.startswith("sky130_fd_pr__")]
    assert banks, f"no model banks reached at all: {incs}"
    for b in banks:
        assert run_sim._sky130_keep_include(b), f"unused bank still parsed: {b}"
    assert any("nfet_01v8__" in b for b in banks)
    assert any("pfet_01v8__" in b for b in banks)


def test_prune_can_be_disabled():
    """The escape hatch must produce a distinct, fuller deck."""
    os.environ["SKY130_PRUNE"] = "0"
    try:
        full = run_sim.sky130_corner_lib("tt")
    finally:
        os.environ.pop("SKY130_PRUNE", None)
    lean = run_sim.sky130_corner_lib("tt")
    assert full != lean
