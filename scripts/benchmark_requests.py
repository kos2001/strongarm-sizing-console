#!/usr/bin/env python3
"""Measure duplicate-request work using real ngspice, with and without sharing.

Run from the repository: python3 scripts/benchmark_requests.py
"""
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_sim


def measure(cache, requests=8):
    with run_sim._ng_lock:
        run_sim._ng_cache.clear()
        run_sim._ng_order.clear()
    barrier = threading.Barrier(requests)
    deck = run_sim.gen_netlist(run_sim._full({}), vdiff=0.01)
    def request(_):
        barrier.wait(timeout=10)
        return run_sim._run(deck, cache=cache)
    start = time.perf_counter()
    with patch.object(run_sim.subprocess, 'run', wraps=run_sim.subprocess.run) as process:
        with ThreadPoolExecutor(max_workers=requests) as pool:
            results = list(pool.map(request, range(requests)))
    decision = run_sim._parse(results[0], 'tdec')
    if decision is None:
        raise RuntimeError('ngspice did not produce a decision-time measurement')
    return {"requests": requests, "subprocesses": process.call_count,
            "seconds": round(time.perf_counter() - start, 6),
            "identical_outputs": len(set(results)) == 1,
            "decision_ps": decision * 1e12}


if __name__ == '__main__':
    print(json.dumps({"simulator": run_sim.NGSPICE,
                      "independent": measure(False), "shared": measure(True)}, indent=2))
