"""Exercise asset delivery over a real socket, without running simulations."""
import gzip
import threading
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest
import server


@pytest.fixture
def site(tmp_path, monkeypatch):
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<html>' + 'console ' * 500 + '</html>')
    (dist / 'assets').mkdir()
    (dist / 'assets' / 'app-hash.js').write_text('const app = 1;\n' * 500)
    outside = tmp_path / 'dist-secret'
    outside.mkdir()
    (outside / 'secret.txt').write_text('private')
    (dist / 'escape.txt').symlink_to(outside / 'secret.txt')
    monkeypatch.setattr(server, 'DIST', str(dist))
    server._static_gz.clear()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    def get(path='/', **headers):
        req = urllib.request.Request(f'http://127.0.0.1:{httpd.server_port}' + path, headers=headers)
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, response.read()
    yield get, dist
    httpd.shutdown()
    httpd.server_close()
    thread.join()


@pytest.mark.parametrize('encoding,compressed', [('gzip', True), ('GZip', True), ('gzip;q=0', False), ('*;q=1, gzip;q=0', False), ('br, *;q=.5', True), ('gzip;q=broken', False), ('identity', False)])
def test_encoding_negotiation(site, encoding, compressed):
    get, dist = site
    status, headers, body = get(**{'Accept-Encoding': encoding})
    assert status == 200
    assert headers['Vary'] == 'Accept-Encoding'
    assert (headers.get('Content-Encoding') == 'gzip') == compressed
    assert int(headers['Content-Length']) == len(body)
    assert (gzip.decompress(body) if compressed else body) == (dist / 'index.html').read_bytes()


def test_revalidation_cache_and_rebuild(site):
    get, dist = site
    _, headers, original = get()
    with patch('builtins.open', side_effect=AssertionError('cached asset reread')):
        assert get()[2] == original
        status, cached_headers, body = get(**{'If-None-Match': headers['ETag'], 'Accept-Encoding': 'gzip'})
    assert status == 304 and body == b''
    assert cached_headers['ETag'] == headers['ETag']
    (dist / 'index.html').write_text('new build')
    status, updated, body = get(**{'If-None-Match': headers['ETag']})
    assert status == 200 and body == b'new build'
    assert updated['ETag'] != headers['ETag']


@pytest.mark.parametrize('path,status', [('/assets/missing.js', 404), ('/missing.css', 404), ('/sizing', 200), ('/../dist-secret/secret.txt', 403), ('/%2e%2e/dist-secret/secret.txt', 403), ('/escape.txt', 403)])
def test_asset_paths(site, path, status):
    assert site[0](path)[0] == status


def test_asset_cache_policy(site):
    get, _ = site
    assert 'immutable' in get('/assets/app-hash.js')[1]['Cache-Control']
    assert 'no-cache' in get('/')[1]['Cache-Control']
