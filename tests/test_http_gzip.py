"""Guards the HTTP response compression in webapp/server.py.

Compression sits on the one path every response leaves by, so a mistake here
corrupts every payload rather than one endpoint. These tests drive a real server
socket and check the bytes on the wire: negotiated correctly, decodable, and
byte-identical to the uncompressed body.
"""
import gzip
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server


@pytest.fixture(scope="module")
def base_url():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def _get(url, gzip_ok):
    req = urllib.request.Request(url)
    # urllib would otherwise advertise identity only
    req.add_header("Accept-Encoding", "gzip" if gzip_ok else "identity")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.headers.get("Content-Encoding"), r.read(), r.headers


def _post(url, payload, gzip_ok):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    req.add_header("Accept-Encoding", "gzip" if gzip_ok else "identity")
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.headers.get("Content-Encoding"), r.read(), r.headers


@pytest.fixture(scope="module")
def pvt(base_url):
    """The 45-corner sign-off payload — the biggest JSON the console fetches,
    and comfortably over the compression threshold."""
    _, plain, _ = _post(base_url + "/api/pvt", {"params": {}}, gzip_ok=False)
    enc, packed, hdrs = _post(base_url + "/api/pvt", {"params": {}}, gzip_ok=True)
    return plain, enc, packed, hdrs


@pytest.mark.parametrize("path", ["/api/health", "/api/defaults"])
def test_small_response_is_not_compressed(base_url, path):
    """Both are under the threshold — gzip would only add framing."""
    enc, body, _ = _get(base_url + path, gzip_ok=True)
    assert enc is None
    assert json.loads(body)          # still valid JSON


def test_uncompressed_request_stays_uncompressed(pvt):
    plain, _, _, _ = pvt
    assert json.loads(plain)["corners"]


def test_large_response_is_compressed_and_decodes_identically(pvt):
    plain, enc, packed, hdrs = pvt
    assert enc == "gzip"
    assert hdrs.get("Vary") == "Accept-Encoding"
    assert gzip.decompress(packed) == plain          # byte-identical, not just equal JSON
    assert len(packed) < len(plain) / 2              # repetitive JSON compresses hard


def test_content_length_matches_the_encoded_body(pvt):
    """A Content-Length left over from the uncompressed body would truncate or
    hang the client — check it against what actually came down."""
    _, _, packed, hdrs = pvt
    assert int(hdrs["Content-Length"]) == len(packed)


def test_pvt_payload_is_intact(pvt):
    plain, _, packed, _ = pvt
    a, b = json.loads(plain), json.loads(gzip.decompress(packed))
    assert a == b
    assert len(a["corners"]) == 45


def test_health_exposes_sim_cache_stats(base_url):
    _, body, _ = _get(base_url + "/api/health", gzip_ok=False)
    stats = json.loads(body)["sim_cache"]
    for k in ("hits", "misses", "size", "max", "max_procs"):
        assert k in stats
