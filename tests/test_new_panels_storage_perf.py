"""Test that newly added storage and perf panels are included in full snapshot events
and remain stable (no spurious updates) when their underlying data is unchanged.
"""
from __future__ import annotations
from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.plugins.base import SummarySnapshot
from scripts.summary.domain import build_domain_snapshot


def make_snap(cycle: int, status: dict, domain=None):
    return SummarySnapshot(status=status, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=cycle, errors=(), model=None, domain=domain, panel_hashes=None)


def test_storage_perf_panels_present_and_stable(monkeypatch):
    pub = SSEPublisher(diff=True)
    status = {
        "indices": ["X"],
        "alerts": {"total": 0},
        "storage": {"lag": 1.23, "queue_depth": 5, "last_flush_age_sec": 12.0},
        "performance": {"foo_latency_ms": 12.5, "bar_rate": 3.14},
        "app": {"version": "1"},
    }
    domain0 = build_domain_snapshot(status)
    pub.process(make_snap(0, status, domain=domain0))
    events = pub.events
    assert events[1]["event"] == "full_snapshot"
    panels = events[1]["data"]["panels"]
    # Hash layer uses keys perfstore + storage; panel providers map to perfstore/storage keys too
    assert "storage" in panels, panels.keys()
    assert "perfstore" in panels, panels.keys()
    # Second cycle with no changes should not emit update for these panels
    domain1 = build_domain_snapshot(status)
    pub.process(make_snap(1, status, domain=domain1))
    # No panel_update referencing storage/perfstore unless other change
    last_evt = pub.events[-1]
    if last_evt["event"] == "panel_update":
        changed = {u["key"] for u in last_evt["data"].get("updates", [])}
        assert not ({"storage", "perfstore"} & changed), f"Unexpected diff for unchanged panels: {changed}"
    elif last_evt["event"] == "panel_diff":
        changed = set((last_evt["data"].get("panels") or {}).keys())
        assert not ({"storage", "perfstore"} & changed), f"Unexpected structured diff for unchanged panels: {changed}"
