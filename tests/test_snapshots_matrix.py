from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
import datetime as dt
import pytest

from src.orchestrator.catalog_http import _CatalogHandler  # type: ignore
from src.domain import snapshots_cache
from src.domain.models import ExpirySnapshot, OptionQuote

# Matrix dimensions / semantics:
# disable_http: if True -> G6_CATALOG_HTTP_DISABLE=1 (expect 410 regardless of cache)
# enable_cache: if True -> G6_SNAPSHOT_CACHE=1 else unset (expect 400 when not disabled)
# populate:    if True -> seed two snapshots (NIFTY, BANKNIFTY) (expect 200 & count>=2)
# index_filter: optional index param to test filtering; only meaningful when 200
#
# Expected outcomes derived from transitional logic in catalog_http._CatalogHandler:
#  - disable_http True => 410 + error snapshots_endpoint_disabled
#  - else if cache disabled => 400 + error snapshot_cache_disabled
#  - else => 200 with JSON {count, snapshots, ...}; index filter prunes list & count.

PARAMS = [
    # disable_http, enable_cache, populate, index_filter, expected_status, expected_error, expected_count_min
    (True,  False, False, None,      410, 'snapshots_endpoint_disabled', None),
    (True,  True,  True,  'NIFTY',   410, 'snapshots_endpoint_disabled', None),  # disable overrides cache
    (False, False, False, None,      400, 'snapshot_cache_disabled',     None),
    (False, False, True,  None,      400, 'snapshot_cache_disabled',     None),  # populate ignored when cache off
    (False, True,  False, None,      200, None,                            0),   # cache on but empty
    (False, True,  True,  None,      200, None,                            2),   # populated
    (False, True,  True,  'NIFTY',   200, None,                            1),   # filtered
]

@pytest.mark.parametrize(
    "disable_http,enable_cache,populate,index_filter,expected_status,expected_error,expected_count_min",
    PARAMS,
)
def test_snapshots_matrix(disable_http, enable_cache, populate, index_filter, expected_status, expected_error, expected_count_min, monkeypatch, http_server_factory):
    # Reset cache
    snapshots_cache._SNAPSHOTS.clear()  # type: ignore[attr-defined]

    # Env setup per scenario
    if disable_http:
        monkeypatch.setenv('G6_CATALOG_HTTP_DISABLE', '1')
    else:
        monkeypatch.delenv('G6_CATALOG_HTTP_DISABLE', raising=False)

    if enable_cache:
        monkeypatch.setenv('G6_SNAPSHOT_CACHE', '1')
    else:
        monkeypatch.delenv('G6_SNAPSHOT_CACHE', raising=False)

    # Basic auth (optional) - not enforced for snapshots path unless configured, but set to ensure no 401 path taken inadvertently
    monkeypatch.setenv('G6_HTTP_BASIC_USER', 'u')
    monkeypatch.setenv('G6_HTTP_BASIC_PASS', 'p')
    auth = base64.b64encode(b'u:p').decode()
    headers = {"Authorization": f"Basic {auth}"}

    # Populate if requested
    if populate:
        now = dt.datetime.now(dt.timezone.utc)
        snap_a = ExpirySnapshot(index='NIFTY', expiry_rule='WEEKLY', expiry_date=now.date(), atm_strike=20000.0, options=[OptionQuote(symbol='NIFTY24SEP20000CE', exchange='NSE', last_price=1.0)], generated_at=now)
        snap_b = ExpirySnapshot(index='BANKNIFTY', expiry_rule='WEEKLY', expiry_date=now.date(), atm_strike=44000.0, options=[OptionQuote(symbol='BANKNIFTY24SEP44000CE', exchange='NSE', last_price=2.0)], generated_at=now)
        snapshots_cache.update([snap_a, snap_b])

    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        target = f"http://127.0.0.1:{port}/snapshots"
        if index_filter:
            target += f"?index={index_filter}"
        req = urllib.request.Request(target, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                body = resp.read().decode('utf-8')
                code = resp.getcode()
        except urllib.error.HTTPError as e:
            code = e.code
            body = e.read().decode('utf-8')
        assert code == expected_status, body

        if expected_status in (400, 410):
            assert expected_error and expected_error in body
        else:
            data = json.loads(body)
            assert 'count' in data and 'snapshots' in data
            # Flexible: exact >= lower bound
            assert data['count'] >= (expected_count_min or 0)
            # If index filter used, ensure all indices match
            if index_filter:
                assert all(s.get('index') == index_filter for s in data['snapshots'])
                assert data['count'] == len(data['snapshots'])
