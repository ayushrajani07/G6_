import os
import base64
import urllib.request
import urllib.error
import datetime as dt

from src.orchestrator.catalog_http import _CatalogHandler  # type: ignore
from src.domain import snapshots_cache
from src.domain.models import ExpirySnapshot, OptionQuote


def _fetch(url: str, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=2) as resp:
        return resp.getcode(), resp.read().decode()


def test_snapshots_endpoint_with_overview_and_auth(monkeypatch, http_server_factory):
    monkeypatch.setenv('G6_SNAPSHOT_CACHE', '1')
    monkeypatch.setenv('G6_HTTP_BASIC_USER', 'u')
    monkeypatch.setenv('G6_HTTP_BASIC_PASS', 'p')

    snapshots_cache._SNAPSHOTS.clear()  # type: ignore[attr-defined]
    # seed snapshot
    snap = ExpirySnapshot(
        index='NIFTY',
        expiry_rule='WEEKLY',
        expiry_date=dt.date.today(),
        atm_strike=20000,
        options=[OptionQuote(symbol='NIFTY24SEP20000CE', exchange='NSE', last_price=1.0)],
        generated_at=dt.datetime.now(dt.timezone.utc),
    )
    snapshots_cache.update([snap])

    with http_server_factory(_CatalogHandler) as httpd:
        port = httpd.server_address[1]
        bad_auth = base64.b64encode(b'u:wrong').decode()
        try:
            _fetch(f'http://127.0.0.1:{port}/snapshots', headers={'Authorization': f'Basic {bad_auth}'})
            assert False, 'Expected HTTPError for wrong password'
        except urllib.error.HTTPError as e:
            assert e.code == 401
        good_auth = base64.b64encode(b'u:p').decode()
        code, body = _fetch(f'http://127.0.0.1:{port}/snapshots', headers={'Authorization': f'Basic {good_auth}'})
        assert code == 200
        assert 'overview' in body and 'snapshots' in body


def test_snapshots_endpoint_disabled(monkeypatch, http_server_factory):
    monkeypatch.delenv('G6_SNAPSHOT_CACHE', raising=False)
    monkeypatch.setenv('G6_HTTP_BASIC_USER', 'u')
    monkeypatch.setenv('G6_HTTP_BASIC_PASS', 'p')

    with http_server_factory(_CatalogHandler) as httpd:
        port = httpd.server_address[1]
        good_auth = base64.b64encode(b'u:p').decode()
        try:
            _fetch(f'http://127.0.0.1:{port}/snapshots', headers={'Authorization': f'Basic {good_auth}'})
            assert False, 'Expected HTTPError 400 for disabled cache'
        except urllib.error.HTTPError as e:
            assert e.code == 400
            body = e.read().decode()
            assert 'snapshot_cache_disabled' in body
