import json, urllib.request as urlreq, urllib.error, time
from datetime import datetime, date, timezone
import pytest
from src.domain.models import OptionQuote, ExpirySnapshot
from src.domain import snapshots_cache


def _make_snapshot(index='NIFTY', rule='this_week'):
    q = OptionQuote(symbol='NIFTY24SEP18000CE', exchange='NSE', last_price=10.5, volume=100, oi=200, timestamp=None, raw={'last_price':10.5})
    return ExpirySnapshot(index=index, expiry_rule=rule, expiry_date=date.today(), atm_strike=18000.0, options=[q], generated_at=datetime.now(timezone.utc))


@pytest.mark.skipif(False, reason="placeholder for global disable gate")
def test_snapshots_endpoint_disabled(catalog_http_server):
    base = catalog_http_server(enable_snapshots=False)
    with pytest.raises(urllib.error.HTTPError) as ei:
        urlreq.urlopen(base + '/snapshots')
    assert ei.value.code == 400  # disabled cache returns 400


def test_snapshots_endpoint_enabled(catalog_http_server):
    snapshots_cache.clear()
    base = catalog_http_server(enable_snapshots=True)
    # Populate cache
    snapshots_cache.update([_make_snapshot('NIFTY'), _make_snapshot('BANKNIFTY')])
    # Poll until available
    target = base + '/snapshots'
    data = {}
    for _ in range(40):
        with urlreq.urlopen(target) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode('utf-8'))
            if data.get('count',0) >= 2:
                break
        time.sleep(0.05)
    assert data.get('count',0) >= 2
    with urlreq.urlopen(target + '?index=NIFTY') as resp:
        data_nifty = json.loads(resp.read().decode('utf-8'))
        assert data_nifty['count'] >= 1
        assert all(s['index']=='NIFTY' for s in data_nifty['snapshots'])
