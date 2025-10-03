import datetime as dt
import os
from collections import defaultdict

from src.storage.csv_sink import CsvSink

# Minimal dummy metrics replicating label/Counter interface used in csv_sink for new metrics
class _CounterHandle:
    def __init__(self, store, key):
        self._store = store
        self._key = key
    def inc(self, amount=1):
        self._store[self._key] += amount
    def set(self, value):  # for gauge semantics
        self._store[self._key] = value

class _DummyCounter:
    def __init__(self, name):
        self.name = name
        self._store = defaultdict(int)
    def labels(self, **labels):
        # convert labels dict to tuple for key stability
        key = tuple(sorted(labels.items()))
        return _CounterHandle(self._store, key)

class _MisclassTestMetrics:
    def __init__(self):
        self.expiry_misclassification_total = _DummyCounter('g6_expiry_misclassification_total')
        self.expiry_canonical_date = _DummyCounter('g6_expiry_canonical_date_info')

    def get_misclass_count(self):
        return sum(self.expiry_misclassification_total._store.values())


def _make_option(symbol, strike, opt_type, price=10.0, vol=100, oi=200):
    return {
        'strike': strike,
        'instrument_type': opt_type,
        'last_price': price,
        'volume': vol,
        'oi': oi,
        'avg_price': price,
    }


def test_expiry_misclassification_detection(tmp_path, monkeypatch):
    """Simulate two writes with differing expiry_date for same (index, expiry_code) and assert metric increments.

    We do not force skipping here (G6_EXPIRY_MISCLASS_SKIP unset) to verify both rows attempt writes but second triggers misclassification counter.
    """
    monkeypatch.delenv('G6_EXPIRY_MISCLASS_SKIP', raising=False)
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_DEBUG','1')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _MisclassTestMetrics(); sink.attach_metrics(metrics)

    ts0 = dt.datetime(2025,9,26,12,0,0)
    # First expiry date establishes canonical mapping
    expiry1 = dt.date(2025,9,30)
    opts = {
        'A1CE': _make_option('A1CE', 100, 'CE'),
        'A1PE': _make_option('A1PE', 100, 'PE'),
    }
    res1 = sink.write_options_data('NIFTY', expiry1, opts, ts0, return_metrics=True)
    assert res1 and 'expiry_code' in res1, 'expiry_code not returned from first write'

    # Second write uses different expiry date but will likely map to same expiry_code classification (e.g., same-week semantics)
    expiry2 = dt.date(2025,10,2)  # different date same week range assumption
    sink.write_options_data('NIFTY', expiry2, opts, ts0 + dt.timedelta(minutes=1))

    # Expect misclassification counter incremented exactly once
    assert metrics.get_misclass_count() == 1, f"Expected 1 misclassification, got {metrics.get_misclass_count()}"


def test_expiry_misclassification_skip_mode(tmp_path, monkeypatch):
    """When G6_EXPIRY_MISCLASS_SKIP=1 the mismatching second row should be skipped (no second data row)."""
    monkeypatch.setenv('G6_EXPIRY_MISCLASS_SKIP','1')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _MisclassTestMetrics(); sink.attach_metrics(metrics)

    ts0 = dt.datetime(2025,9,26,12,0,0)
    expiry1 = dt.date(2025,9,30)
    opts = {
        'B1CE': _make_option('B1CE', 100, 'CE'),
        'B1PE': _make_option('B1PE', 100, 'PE'),
    }
    sink.write_options_data('NIFTY', expiry1, opts, ts0)
    # second conflicting date
    expiry2 = dt.date(2025,10,2)
    sink.write_options_data('NIFTY', expiry2, opts, ts0 + dt.timedelta(minutes=1))

    # misclassification counter increments even in skip mode
    assert metrics.get_misclass_count() == 1

    # Verify only one data row persisted
    out_dir = tmp_path / 'NIFTY'
    csv_files = list(out_dir.rglob('*.csv'))
    # There should be exactly one file; inside it only 2 lines (header + first row)
    assert len(csv_files) == 1, f"Unexpected file count: {csv_files}"
    lines = csv_files[0].read_text().splitlines()
    assert len(lines) == 2, f"Expected 2 lines (header+row) got {len(lines)}"
