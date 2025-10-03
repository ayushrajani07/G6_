import os
from src.metrics import get_metrics  # facade import
import src.analytics.vol_surface as vs

class DummySnapshotSource:
    def __init__(self, options, metrics):
        self._options = options
        self.metrics = metrics
    def iter_options(self):
        for o in self._options:
            yield o

# Mirror helper from existing follow-on test (lightweight dummy option)

def _dummy_option(expiry="2025-01-01", strike=100, underlying=100, iv=0.2, index="NIFTY"):
    return {
        'index': index,
        'expiry': expiry,
        'strike': strike,
        'underlying': underlying,
        'iv': iv,
    }

def test_per_expiry_metrics_absent_when_flag_off(monkeypatch):
    # Ensure flags: surface on, per-expiry off
    monkeypatch.setenv('G6_VOL_SURFACE', '1')
    monkeypatch.delenv('G6_VOL_SURFACE_PER_EXPIRY', raising=False)
    metrics = get_metrics()
    # Build small surface
    opts = [
        _dummy_option(expiry='2025-01-01', strike=100, iv=0.21),
        _dummy_option(expiry='2025-02-01', strike=105, iv=0.23),
    ]
    snap = DummySnapshotSource(opts, metrics)
    surface = vs.build_surface(snap)
    assert surface is not None
    assert not hasattr(metrics, 'vol_surface_rows_expiry'), 'Per-expiry rows gauge should NOT exist when flag off'
    assert not hasattr(metrics, 'vol_surface_interpolated_fraction_expiry'), 'Per-expiry fraction gauge should NOT exist when flag off'
