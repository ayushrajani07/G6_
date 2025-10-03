import base64
import urllib.request
import urllib.error

from src.orchestrator.catalog_http import _CatalogHandler  # type: ignore


def _fetch(url: str, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.getcode(), resp.read().decode()


def test_basic_auth_protects_catalog(monkeypatch, http_server_factory):
    monkeypatch.setenv("G6_HTTP_BASIC_USER", "user")
    monkeypatch.setenv("G6_HTTP_BASIC_PASS", "pass")
    # disable snapshot cache to simplify
    monkeypatch.delenv("G6_SNAPSHOT_CACHE", raising=False)

    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        # without auth -> 401
        try:
            _fetch(f"http://127.0.0.1:{port}/catalog")
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 401
            assert e.headers.get("WWW-Authenticate", "").startswith("Basic")
        # with wrong creds -> 401
        bad_auth = base64.b64encode(b"user:wrong").decode()
        try:
            _fetch(f"http://127.0.0.1:{port}/catalog", headers={"Authorization": f"Basic {bad_auth}"})
            assert False, "Expected HTTPError"
        except urllib.error.HTTPError as e:
            assert e.code == 401
        # with correct creds -> 200 (catalog may 500 if build fails; tolerate 200 or 500?) Expect 200 ideally.
        good_auth = base64.b64encode(b"user:pass").decode()
        code, body = _fetch(f"http://127.0.0.1:{port}/catalog", headers={"Authorization": f"Basic {good_auth}"})
        assert code == 200, body


def test_health_endpoint_unprotected(monkeypatch, http_server_factory):
    monkeypatch.setenv("G6_HTTP_BASIC_USER", "user")
    monkeypatch.setenv("G6_HTTP_BASIC_PASS", "pass")
    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        code, body = _fetch(f"http://127.0.0.1:{port}/health")
        assert code == 200
        assert 'status' in body
