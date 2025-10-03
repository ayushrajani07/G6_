import io
import sys
from scripts.summary.plain_renderer import PlainRenderer
from scripts.summary.plugins.base import SummarySnapshot


def make_snap(raw=None):
    raw = raw or {"cycle": {"number": 1}, "indices": ["A"], "alerts": {"total": 0}, "resources": {}}
    return SummarySnapshot(status=raw, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=0, errors=tuple(), model=None, domain=None)


def test_plain_renderer_diff_suppresses_second(monkeypatch):
    r = PlainRenderer()
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    snap = make_snap()
    r.process(snap)
    first = buf.getvalue()
    assert '[Cycle]' in first
    buf.truncate(0); buf.seek(0)
    r.process(snap)
    second = buf.getvalue()
    assert second == ''  # suppressed identical frame


def test_plain_renderer_diff_disable(monkeypatch):
    import os
    os.environ['G6_SUMMARY_PLAIN_DIFF'] = '0'
    r = PlainRenderer()
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)
    snap = make_snap()
    r.process(snap)
    buf.truncate(0); buf.seek(0)
    r.process(snap)
    # With diff disabled we expect output again
    assert buf.getvalue() != ''
