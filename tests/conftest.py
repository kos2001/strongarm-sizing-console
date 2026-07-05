"""Shared fixtures / path setup for the StrongARM regression tests.

Tests exercise the real ngspice backend, so they are integration tests: they
are skipped automatically if ngspice is not on the machine.
"""
import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)                       # strongarm_sim/
sys.path.insert(0, os.path.join(ROOT, "webapp"))  # webapp/ (server.py)

import run_sim  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _require_ngspice():
    if not (shutil.which(run_sim.NGSPICE) or os.path.exists(run_sim.NGSPICE)):
        pytest.skip("ngspice not installed", allow_module_level=False)
