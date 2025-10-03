import datetime as dt
import os
from src.storage.csv_sink import CsvSink
from collections import defaultdict


class _CounterHandle:
    def __init__(self, store, key):
        self._store = store
        self._key = key
    def inc(self, amount=1):
        self._store[self._key] += amount

class _DummyCounter:
    def __init__(self, name):
        self.name = name
        self._store = defaultdict(int)  # (index, expiry) -> value
    def labels(self, *, index, expiry):  # match keyword usage in csv_sink
        return _CounterHandle(self._store, (index, expiry))
    # minimal collect() interface if needed elsewhere
    def collect(self):  # pragma: no cover - not used in assertions now
        class Sample:
            __slots__ = ('name','labels','value')
            def __init__(self, name, labels, value):
                self.name = name
                self.labels = labels
                self.value = value
        class MetricObj:
            def __init__(self, samples):
                self.samples = samples
        samples = [Sample(self.name, {'index': i, 'expiry': e}, v) for (i,e),v in self._store.items()]
        return [MetricObj(samples)]

class _JunkTestMetrics:
    """Pure-Python minimal metrics registry for junk filter tests.

    Avoids Prometheus client counter semantics (which append _total/_created samples)
    so that counts remain small integers and deterministic.
    """
    def __init__(self):
        self.csv_junk_rows_skipped = _DummyCounter('g6_csv_junk_rows_skipped_total')
        self.csv_junk_rows_threshold = _DummyCounter('g6_csv_junk_rows_threshold_skipped_total')
        self.csv_junk_rows_stale = _DummyCounter('g6_csv_junk_rows_stale_skipped_total')
    def _sum(self, counter, index):
        return sum(v for (i,_e),v in counter._store.items() if i == index)
    def get_total_skips(self, index):
        return self._sum(self.csv_junk_rows_skipped, index)
    def get_stale_skips(self, index):
        return self._sum(self.csv_junk_rows_stale, index)
    def get_threshold_skips(self, index):
        return self._sum(self.csv_junk_rows_threshold, index)


def _make_option(symbol, strike, opt_type, price=0.0, vol=0, oi=0):
    return {
        'strike': strike,
        'instrument_type': opt_type,
        'last_price': price,
        'volume': vol,
        'oi': oi,
        'avg_price': price,
    }

def test_junk_filter_skips_low_oi_and_volume(tmp_path, monkeypatch):
    # Configure junk thresholds
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','10')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_VOL','5')
    # Auto enable (thresholds make it on)
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _JunkTestMetrics()
    sink.attach_metrics(metrics)

    ts = dt.datetime(2025,9,26,12,0,0)
    expiry = dt.date(2025,9,27)

    # Row below thresholds: total oi=2, vol=2 -> skipped
    opts_low = {
        'SYM1CE': _make_option('SYM1CE', 100, 'CE', price=1.0, vol=1, oi=1),
        'SYM1PE': _make_option('SYM1PE', 100, 'PE', price=1.5, vol=1, oi=1),
    }
    sink.write_options_data('NIFTY', expiry, opts_low, ts)

    # Row meeting thresholds: total oi=20, vol=10 -> written
    opts_ok = {
        'SYM2CE': _make_option('SYM2CE', 150, 'CE', price=2.0, vol=5, oi=10),
        'SYM2PE': _make_option('SYM2PE', 150, 'PE', price=2.5, vol=5, oi=10),
    }
    sink.write_options_data('NIFTY', expiry, opts_ok, ts + dt.timedelta(minutes=1))

    # Verify junk skip metric incremented exactly once
    # Access internal counter value via private structure
    skipped = metrics.get_total_skips('NIFTY')
    assert skipped == 1, f"Expected 1 junk skip, got {skipped}"

    # Verify only second row file exists with content
    out_dir = tmp_path / 'NIFTY'
    assert out_dir.exists()
    # find csv files
    csv_files = list(out_dir.rglob('*.csv'))
    # Should have exactly one data file under strike offset directory where second row written
    assert len(csv_files) == 1, f"Unexpected files: {csv_files}"
    content = csv_files[0].read_text().splitlines()
    # header + 1 data row
    assert len(content) == 2


def test_junk_filter_disabled_when_thresholds_zero(tmp_path, monkeypatch):
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','0')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_VOL','0')
    monkeypatch.setenv('G6_CSV_JUNK_ENABLE','auto')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _JunkTestMetrics()
    sink.attach_metrics(metrics)
    ts = dt.datetime(2025,9,26,12,0,0)
    expiry = dt.date(2025,9,27)

    opts_low = {
        'SYM1CE': _make_option('SYM1CE', 100, 'CE', price=1.0, vol=0, oi=0),
        'SYM1PE': _make_option('SYM1PE', 100, 'PE', price=1.5, vol=0, oi=0),
    }
    sink.write_options_data('NIFTY', expiry, opts_low, ts)
    # With thresholds zero and auto mode -> junk filter disabled; row written
    out_dir = tmp_path / 'NIFTY'
    csv_files = list(out_dir.rglob('*.csv'))
    assert len(csv_files) == 1
    content = csv_files[0].read_text().splitlines()
    assert len(content) == 2  # header + row


def test_junk_filter_stale_skip(monkeypatch, tmp_path):
    # Enable stale detection only (ensure debug on for diagnosis if needed)
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','0')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_VOL','0')
    monkeypatch.setenv('G6_CSV_JUNK_ENABLE','auto')  # auto relies on stale threshold
    monkeypatch.setenv('G6_CSV_JUNK_STALE_THRESHOLD','2')  # allow 2 same, skip from 3rd identical onwards
    monkeypatch.setenv('G6_CSV_JUNK_DEBUG','1')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _JunkTestMetrics()
    sink.attach_metrics(metrics)
    ts = dt.datetime(2025,9,26,12,0,0)
    expiry = dt.date(2025,9,27)
    base_opts = {
        'SYMCE': _make_option('SYMCE', 100, 'CE', price=5.0, vol=10, oi=10),
        'SYMPE': _make_option('SYMPE', 100, 'PE', price=7.0, vol=12, oi=12),
    }
    sink.write_options_data('NIFTY', expiry, base_opts, ts)
    sink.write_options_data('NIFTY', expiry, base_opts, ts + dt.timedelta(seconds=30))
    sink.write_options_data('NIFTY', expiry, base_opts, ts + dt.timedelta(seconds=60))
    stale_skips = metrics.get_stale_skips('NIFTY')
    total_skips = metrics.get_total_skips('NIFTY')
    assert stale_skips == 1, f"Expected 1 stale skip, got {stale_skips}"
    assert total_skips == 1, f"Expected aggregate skips 1, got {total_skips}"
    out_dir = tmp_path / 'NIFTY'
    csv_files = list(out_dir.rglob('*.csv'))
    assert len(csv_files) == 1
    lines = csv_files[0].read_text().splitlines()
    assert len(lines) == 3


def test_junk_filter_whitelist_bypass(monkeypatch, tmp_path):
    # Set thresholds and stale, but whitelist symbol
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','50')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_VOL','25')
    monkeypatch.setenv('G6_CSV_JUNK_STALE_THRESHOLD','1')
    monkeypatch.setenv('G6_CSV_JUNK_WHITELIST','NIFTY:*')  # bypass all filtering for NIFTY
    monkeypatch.setenv('G6_CSV_JUNK_DEBUG','1')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _JunkTestMetrics()

def test_junk_filter_whitelist_variants(monkeypatch, tmp_path):
    """Ensure all documented whitelist pattern forms bypass junk filtering.

    Patterns exercised:
      * global '*'
      * INDEX:* form
      * *:expiry_code form (simulate by providing expiry code via rule tag)
    """
    base_opts = {
        'SYMA': _make_option('SYMA', 100, 'CE', price=1.0, vol=0, oi=0),
        'SYMB': _make_option('SYMB', 100, 'PE', price=1.2, vol=0, oi=0),
    }
    ts = dt.datetime(2025,9,26,12,0,0)
    expiry = dt.date(2025,9,27)

    # Case 1: global '*'
    monkeypatch.setenv('G6_CSV_JUNK_WHITELIST','*')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','50')
    sink = CsvSink(base_dir=str(tmp_path/ 'case1'))
    m1 = _JunkTestMetrics(); sink.attach_metrics(m1)
    sink.write_options_data('NIFTY', expiry, base_opts, ts)
    assert m1.get_total_skips('NIFTY') == 0

    # Case 2: INDEX:* form
    monkeypatch.setenv('G6_CSV_JUNK_WHITELIST','NIFTY:*')
    sink2 = CsvSink(base_dir=str(tmp_path/ 'case2'))
    m2 = _JunkTestMetrics(); sink2.attach_metrics(m2)
    sink2.write_options_data('NIFTY', expiry, base_opts, ts)
    assert m2.get_total_skips('NIFTY') == 0

    # Case 3: *:expiry_code form. We need to know expiry_code used by sink heuristic (e.g., next/this_week etc.).
    # We'll fetch it by first writing once with no whitelist, then reuse pattern.
    monkeypatch.delenv('G6_CSV_JUNK_WHITELIST', raising=False)
    sink3 = CsvSink(base_dir=str(tmp_path/ 'case3'))
    m3 = _JunkTestMetrics(); sink3.attach_metrics(m3)
    # Low thresholds to force classification as junk if not whitelisted
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','10')
    res = sink3.write_options_data('NIFTY', expiry, base_opts, ts, return_metrics=True)
    assert res is not None, 'Expected metrics dict when return_metrics=True'
    expiry_code = res.get('expiry_code')
    assert expiry_code, 'expiry_code not found in returned metrics'
    # Now whitelist *:expiry_code BEFORE second write so it is bypassed
    monkeypatch.setenv('G6_CSV_JUNK_WHITELIST', f'*:{expiry_code}')
    # Invalidate cached junk config so whitelist is reloaded
    if hasattr(sink3, '_junk_cfg_loaded'):
        delattr(sink3, '_junk_cfg_loaded')
    sink3.write_options_data('NIFTY', expiry, base_opts, ts + dt.timedelta(minutes=1))
    # Only the first (pre-whitelist) write should count as skip
    assert m3.get_total_skips('NIFTY') == 1, f"Expected only initial skip, got {m3.get_total_skips('NIFTY')}"

def test_junk_filter_summary_emission(monkeypatch, tmp_path, caplog):
    """Validate that a summary log line is emitted after interval when skips accumulate."""
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','10')
    monkeypatch.setenv('G6_CSV_JUNK_SUMMARY_INTERVAL','1')  # 1 second window
    monkeypatch.setenv('G6_CSV_JUNK_DEBUG','1')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _JunkTestMetrics(); sink.attach_metrics(metrics)
    ts0 = dt.datetime(2025,9,26,12,0,0)
    expiry = dt.date(2025,9,27)
    low_row = {
        'A1CE': _make_option('A1CE', 100, 'CE', price=1.0, vol=1, oi=1),
        'A1PE': _make_option('A1PE', 100, 'PE', price=1.2, vol=1, oi=1),
    }
    with caplog.at_level('INFO'):
        sink.write_options_data('NIFTY', expiry, low_row, ts0)
        # Advance artificial time by sleeping just over interval to trigger summary on next skip
        import time as _t; _t.sleep(1.1)
        sink.write_options_data('NIFTY', expiry, low_row, ts0 + dt.timedelta(seconds=30))
    # We expect at least one CSV_JUNK_SUMMARY line present
    summaries = [r for r in caplog.messages if 'CSV_JUNK_SUMMARY' in r]
    assert summaries, 'Expected a CSV_JUNK_SUMMARY log line after interval'


def test_junk_filter_per_leg_thresholds(monkeypatch, tmp_path):
    """Rows should be skipped if either leg fails per-leg oi/vol floors even if combined totals pass."""
    monkeypatch.setenv('G6_CSV_JUNK_MIN_LEG_OI','10')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_LEG_VOL','5')
    # generous combined thresholds so only per-leg logic governs
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_OI','1')
    monkeypatch.setenv('G6_CSV_JUNK_MIN_TOTAL_VOL','1')
    sink = CsvSink(base_dir=str(tmp_path))
    metrics = _JunkTestMetrics(); sink.attach_metrics(metrics)
    ts = dt.datetime(2025,9,26,12,0,0)
    expiry = dt.date(2025,9,27)
    # CE meets, PE below -> skip
    opts = {
        'XCE': _make_option('XCE',100,'CE',price=2.0,vol=6,oi=12),
        'XPE': _make_option('XPE',100,'PE',price=2.5,vol=1,oi=3),
    }
    sink.write_options_data('NIFTY', expiry, opts, ts)
    assert metrics.get_total_skips('NIFTY') == 1
    # Raise the weak leg above thresholds -> written
    opts2 = {
        'XCE': _make_option('XCE',100,'CE',price=2.1,vol=6,oi=12),
        'XPE': _make_option('XPE',100,'PE',price=2.6,vol=5,oi=11),
    }
    sink.write_options_data('NIFTY', expiry, opts2, ts + dt.timedelta(minutes=1))
    # Expect only second row file present
    out_dir = tmp_path / 'NIFTY'
    csv_files = list(out_dir.rglob('*.csv'))
    assert len(csv_files) == 1
    lines = csv_files[0].read_text().splitlines()
    assert len(lines) == 2  # header + second row
