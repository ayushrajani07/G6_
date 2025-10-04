"""Test SSEPublisher subset optimization logic.

Ensures that when only one panel hash changes after initial snapshot,
we emit a single panel_update containing only that panel and avoid
building unrelated panels (heuristic: others absent from updates).
"""
from __future__ import annotations

from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.plugins.base import SummarySnapshot


def make_snap(cycle, status):
    return SummarySnapshot(status=status, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=cycle, errors=(), model=None, domain=None, panel_hashes=None)


def test_subset_only_changed_panel(monkeypatch):
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES','5')
    pub = SSEPublisher(diff=True)
    base_status = {"indices": ["A"], "alerts": {"total": 0}, "resources": {"cpu_pct": 10.0, "memory_mb": 100.0}, "app": {"version": "1"}}
    # initial cycle
    pub.process(make_snap(0, base_status))
    # mutate only alerts
    changed_status = {"indices": ["A"], "alerts": {"total": 1}, "resources": {"cpu_pct": 10.0, "memory_mb": 100.0}, "app": {"version": "1"}}
    pub.process(make_snap(1, changed_status))
    evts = pub.events
    # last event should be panel_update or panel_diff with only alerts
    last = evts[-1]
    if last['event'] == 'panel_update':
        ups = last['data']['updates']
        keys = {u['key'] for u in ups}
        assert keys == {'alerts'}, f"unexpected keys {keys}"
    elif last['event'] == 'panel_diff':
        keys = set(last['data']['panels'].keys())
        assert keys == {'alerts'}, f"unexpected keys {keys}"
    else:
        raise AssertionError(f"Unexpected last event {last['event']}")
