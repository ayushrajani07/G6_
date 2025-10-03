import os
from src.metrics import get_metrics  # facade import
from src.analytics import vol_surface as vs
from src.analytics import risk_agg as ra

def _dummy_option(index='NIFTY', expiry='2025-01-01', strike=100, underlying=100, iv=0.2):
    return {'index': index, 'expiry': expiry, 'strike': strike, 'underlying': underlying, 'iv': iv}

def _dummy_greek(index='NIFTY', expiry='2025-01-01', strike=100, underlying=100, delta=1, gamma=0.1, vega=0.5, theta=-0.1, rho=0.01):
    return {'index': index, 'expiry': expiry, 'strike': strike, 'underlying': underlying, 'delta': delta, 'gamma': gamma, 'vega': vega, 'theta': theta, 'rho': rho}

class DummySnapshotSource:
    def __init__(self, options, metrics):
        self._options = options
        self.metrics = metrics
    def get_option_snapshots(self):
        return self._options

def test_per_expiry_vol_surface_and_bucket_utilization(monkeypatch):
    os.environ['G6_VOL_SURFACE'] = '1'
    os.environ['G6_VOL_SURFACE_PER_EXPIRY'] = '1'
    os.environ['G6_RISK_AGG'] = '1'
    metrics = get_metrics()
    # Create two expiries with a mix of strikes to produce two buckets at least
    opts = [
        _dummy_option(expiry='2025-01-01', strike=100, underlying=100, iv=0.2),
        _dummy_option(expiry='2025-01-01', strike=105, underlying=100, iv=0.22),
        _dummy_option(expiry='2025-02-01', strike=95, underlying=100, iv=0.19),
        _dummy_option(expiry='2025-02-01', strike=110, underlying=100, iv=0.25),
    ]
    snap = DummySnapshotSource(opts, metrics)
    surface = vs.build_surface(snap)
    assert surface is not None
    # Expect per-expiry metrics present
    per_expiry_rows = getattr(metrics, 'vol_surface_rows_expiry', None)
    assert per_expiry_rows is not None, 'Expected per-expiry rows gauge'
    # Access one label combination
    child = per_expiry_rows.labels(index='global', expiry='2025-01-01', source='raw')
    val = child._value.get()  # type: ignore[attr-defined]
    assert val >= 1

    # Risk aggregation with basic greeks to exercise utilization metric
    greeks = [
        _dummy_greek(strike=100, underlying=100),
        _dummy_greek(strike=105, underlying=100),
        _dummy_greek(strike=95, underlying=100),
    ]
    snap2 = DummySnapshotSource(greeks, metrics)
    risk = ra.build_risk(snap2)
    assert risk is not None
    util_g = getattr(metrics, 'risk_agg_bucket_utilization', None)
    assert util_g is not None, 'Expected bucket utilization gauge'
    util_val = util_g._value.get()  # type: ignore[attr-defined]
    assert 0 <= util_val <= 1

    # Cleanup env
    for k in ['G6_VOL_SURFACE','G6_VOL_SURFACE_PER_EXPIRY','G6_RISK_AGG']:
        os.environ.pop(k, None)
