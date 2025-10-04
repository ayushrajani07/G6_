import os, io, sys
from scripts.summary.plugins.base import SummarySnapshot, TerminalRenderer
from scripts.summary.summary_metrics import snapshot as metrics_snapshot


def _make_snap(panel_hashes: dict[str,str] | None = None):
    # Minimal status with indices & alerts for hashing context
    status = {"indices": ["A"], "alerts": [], "app": {"version": "1"}}
    return SummarySnapshot(status=status, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=1, errors=tuple(), model=None, domain=None, panel_hashes=panel_hashes)


def test_terminal_renderer_metrics_updates(monkeypatch):
    os.environ['G6_SUMMARY_RICH_DIFF'] = '1'
    # Provide two different hash sets across cycles to force an update
    h1 = {"header": "aaa", "indices": "bbb", "alerts": "ccc", "analytics": "ddd", "links": "static", "perfstore": "eee", "storage": "fff"}
    h2 = {**h1, "alerts": "ccc2"}  # only alerts changes
    buf = io.StringIO()
    monkeypatch.setattr(sys, 'stdout', buf)  # guard if any print
    r = TerminalRenderer(rich_enabled=False)  # disable rich layout; we only need diff logic counters
    # First cycle (baseline)
    r.process(_make_snap(h1))
    # Second cycle triggers one panel change (alerts)
    r.process(_make_snap(h2))
    m = metrics_snapshot()
    # Expect one counter increment for alerts panel
    alert_counter_keys = [k for k in m['counter'].keys() if 'g6_summary_panel_updates_total' in k[0] or 'panel_updates_total' in k[0]]
    # More portable: look for any counter label tuple containing alerts
    has_alerts = any(any(lbl[1] == 'alerts' for lbl in k[1]) for k in m['counter'])
    assert has_alerts, f"alerts panel update counter missing: keys={m['counter'].keys()}"
    # Hit ratio gauge should exist
    assert 'g6_summary_diff_hit_ratio' in m['gauge']
    # Last updates gauge should be 1
    assert m['gauge'].get('g6_summary_panel_updates_last') == 1


def test_metrics_no_hashes_disables_diff(monkeypatch):
    os.environ['G6_SUMMARY_RICH_DIFF'] = '1'
    r = TerminalRenderer(rich_enabled=False)
    snap = _make_snap(panel_hashes=None)
    r.process(snap)  # Should disable diff silently
    # Metrics snapshot should not show panel updates last (or zero) because no hashes
    m = metrics_snapshot()
    # Allowed: missing gauge means no emission; treat as pass
    # If present ensure it's 0
    val = m['gauge'].get('g6_summary_panel_updates_last')
    if val is not None:
        assert val in (0,)
