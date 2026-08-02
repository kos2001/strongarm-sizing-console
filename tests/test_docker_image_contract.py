"""What the container image has to get right, asserted on the host so it fails fast.

The image is built around ngspice rather than around the web app, and two of the four
device-model backends are conditional inside it. Both facts have sharp edges:

  - the server bound 127.0.0.1 unconditionally, which inside a container means the published
    port reaches nothing;
  - `bsimcmg107.osdi` is a NATIVE shared library, so the vendored macOS build cannot load on
    Linux — and a wrong-architecture OSDI surfaces as a raw ngspice parse error from inside a
    sizing run, which reads as "the simulator is broken" rather than "this backend is not
    installed here".

These tests pin the contract that makes both diagnosable.
"""
import os
import re
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "webapp"))

import run_sim  # noqa: E402


def test_availability_names_every_backend_and_a_reason_when_absent():
    a = run_sim.model_availability()
    assert set(a["models"]) == {"ptm45", "gaa2nm", "asap7", "sky130"}
    assert a["ngspice"]["available"] is True
    for name, st in a["models"].items():
        assert isinstance(st["available"], bool), name
        # an unavailable backend without a reason is the failure mode this replaces
        if not st["available"]:
            assert st["reason"], name
            assert len(st["reason"]) > 20, (name, st["reason"])
    # the vendored backends must always be present — they are the image's baseline
    assert a["models"]["ptm45"]["available"] is True
    assert a["models"]["gaa2nm"]["available"] is True


def test_the_osdi_check_looks_at_the_binary_not_just_the_path(tmp_path, monkeypatch):
    """A file at the right path but built for another platform must NOT report available."""
    fake = tmp_path / "bsimcmg107.osdi"
    fake.write_bytes(b"\xcf\xfa\xed\xfe" + b"\x00" * 64)      # Mach-O magic
    monkeypatch.setattr(run_sim, "ASAP7_OSDI", str(fake))
    monkeypatch.setattr("platform.system", lambda: "Linux")
    st = run_sim.model_availability()["models"]["asap7"]
    assert st["available"] is False
    assert "macOS" in st["reason"] and "Linux" in st["reason"]

    fake.write_bytes(b"\x7fELF" + b"\x00" * 64)               # ELF magic
    assert run_sim.model_availability()["models"]["asap7"]["available"] is True


def test_sky130_reports_the_path_it_looked_for(monkeypatch):
    """"PDK not found" is only actionable if it says where it looked and what to set."""
    monkeypatch.setenv("SKY130_NGSPICE_LIB", "/nope/sky130.lib.spice")
    st = run_sim.model_availability()["models"]["sky130"]
    assert st["available"] is False
    assert "/nope/sky130.lib.spice" in st["reason"]
    assert "SKY130_NGSPICE_LIB" in st["reason"]


def test_the_server_can_bind_a_non_loopback_address():
    """127.0.0.1 inside a container publishes nothing. The bind address must be settable
    without a custom command, since the image's CMD is plain `python webapp/server.py`."""
    src = open(os.path.join(ROOT, "webapp", "server.py")).read()
    assert 'os.environ.get("STRONGARM_HOST")' in src
    assert 'ThreadingHTTPServer((HOST, PORT)' in src
    assert '("127.0.0.1", PORT)' not in src          # the hardcoded bind is gone
    assert 'os.environ.get("STRONGARM_PORT")' in src


def test_health_exposes_availability():
    import server
    assert hasattr(run_sim, "model_availability")
    src = open(os.path.join(ROOT, "webapp", "server.py")).read()
    h = src[src.index('if path == "/api/health"'):]
    h = h[:h.index('elif path ==')]
    assert "model_availability()" in h
    assert "availability" in h
    del server


@pytest.mark.parametrize("path", ["Dockerfile", ".dockerignore", "docker-compose.yml",
                                  "requirements.txt"])
def test_the_build_files_exist(path):
    assert os.path.exists(os.path.join(ROOT, path)), path


def test_the_image_pins_the_simulator_version():
    """Every measurement in the README was taken on ngspice-46. An unpinned simulator
    silently changes the numbers, so the version is a build arg with an explicit default."""
    df = open(os.path.join(ROOT, "Dockerfile")).read()
    m = re.search(r"ARG NGSPICE_VERSION=(\d+)", df)
    assert m and m.group(1) == "46", df[:200]
    assert "--enable-osdi" in df          # what makes the asap7 backend possible at all
    assert "npm run build" in df          # frontend built in-image, and it typechecks


def test_the_context_excludes_the_heavy_toolchains_but_keeps_the_va_source():
    """Without this the build context is 1.1 GB, nearly all of it a Rust/LLVM compiler.
    The Verilog-A source must survive the exclusion — it is what the OSDI rebuild needs."""
    # patterns only: a naive split() also picks up the word "third_party" out of the
    # explanatory comment, which made this assertion fail on the file it was describing
    ig = [ln.strip() for ln in open(os.path.join(ROOT, ".dockerignore"))
          if ln.strip() and not ln.lstrip().startswith("#")]
    assert "third_party/OpenVAF" in ig
    assert "third_party/spicelib-mcp" in ig
    # excluding third_party wholesale would take the Verilog-A source with it
    assert "third_party" not in ig and "third_party/" not in ig
    assert "models/asap7/bsimcmg107.osdi" in ig       # host-only, wrong arch for Linux
    df = open(os.path.join(ROOT, "Dockerfile")).read()
    assert "third_party/bsimcmg107/" in df
