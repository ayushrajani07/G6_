import io
import sys
from scripts.summary.plain_renderer import PlainRenderer
from scripts.summary.plugins.base import SummarySnapshot


def _make_snapshot(raw=None):
    if raw is None:  # Only substitute defaults if not explicitly provided
        raw = {
            "cycle": {"number": 5, "duration": 0.2, "success_rate": 90.0},
            "indices": ["X", "Y"],
            "alerts": {"total": 2, "severity_counts": {"warn": 2}},
            "resources": {"cpu_pct": 2.5, "memory_mb": 128.0},
        }
    return SummarySnapshot(status=raw, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=0, errors=tuple(), model=None)


def test_plain_renderer_outputs_panels_in_order(monkeypatch):
    renderer = PlainRenderer(max_width=120)
    snap = _make_snapshot()
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    renderer.process(snap)
    out = buf.getvalue().strip().splitlines()
    # Expect panel headers in registry default order
    headers = [l for l in out if l.startswith('[') and l.endswith(']')]
    assert headers[:4] == ['[Cycle]', '[Indices]', '[Alerts]', '[Resources]']


def test_plain_renderer_graceful_on_missing_fields(monkeypatch):
    renderer = PlainRenderer(max_width=80)
    snap = _make_snapshot(raw={})
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    renderer.process(snap)
    out = buf.getvalue()
    assert '[Cycle]' in out
    assert 'cycle: —' in out
