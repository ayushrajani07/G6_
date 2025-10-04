import json, os, tempfile, time
from pathlib import Path

from src.orchestrator.status_writer import write_runtime_status

class DummyProviders:
    primary_provider = None
    def get_ltp(self, idx):
        return 100.0
    def get_index_data(self, idx):
        return 100.0, None

class DummySink: ...

class DummyMetrics:
    _adaptive_current_mode = 1  # band
    def __init__(self):
        self.runtime_status_writes = type('C', (), {'inc': lambda self: None})()
        self.runtime_status_last_write_unixtime = type('G', (), {'set': lambda self, v: None})()


def _write_status(tmp_path: Path, mode: int, band_window: int):
    m = DummyMetrics()
    m._adaptive_current_mode = mode
    os.environ['G6_DETAIL_MODE_BAND_ATM_WINDOW'] = str(band_window)
    write_runtime_status(
        path=str(tmp_path),
        cycle=5,
        elapsed=0.12,
        interval=1.0,
        index_params={'NIFTY': {}},
        providers=DummyProviders(),
        csv_sink=DummySink(),
        influx_sink=DummySink(),
        metrics=m,
        readiness_ok=True,
        readiness_reason='',
        health_monitor=None,
    )
    with open(tmp_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def test_runtime_status_contains_detail_mode_and_band():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'status.json'
        obj = _write_status(p, mode=1, band_window=3)
        assert obj.get('option_detail_mode') == 1
        assert obj.get('option_detail_mode_str') == 'band'
        assert obj.get('option_detail_band_window') == 3


def test_panels_factory_includes_adaptive_panel():
    from src.utils.status_reader import get_status_reader
    from src.panels.factory import build_panels
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'status.json'
        _ = _write_status(p, mode=2, band_window=0)
        reader = get_status_reader(str(p))
        status = reader.get_raw_status()
        panels = build_panels(reader, status)
        assert 'adaptive' in panels
        adap = panels['adaptive']
        assert adap.get('detail_mode') == 2
        assert adap.get('detail_mode_str') == 'agg'


def test_plain_renderer_renders_cycle_and_indices():
    from scripts.summary.plain_renderer import PlainRenderer
    from scripts.summary.domain import build_domain_snapshot
    from scripts.summary.plugins.base import SummarySnapshot
    status = {'indices': ['NIFTY'], 'cycle': 5}
    domain = build_domain_snapshot(status, ts_read=0.0)
    snap = SummarySnapshot(status=status, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=5, errors=[], model=None, domain=domain)
    import io, sys
    buf, old = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        PlainRenderer().process(snap)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert 'NIFTY' in out
    assert 'Cycle' in out or 'cycle' in out

import pytest
@pytest.mark.skip(reason="Legacy plain_fallback detail mode test removed (summary_view deleted)")
def test_legacy_plain_fallback_deprecated():  # pragma: no cover - intentionally skipped
    assert True
