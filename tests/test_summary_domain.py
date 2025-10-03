import time
from scripts.summary.domain import build_domain_snapshot, CycleInfo, AlertsInfo, ResourceInfo, CoverageInfo


def test_build_domain_snapshot_empty():
    snap = build_domain_snapshot(None, ts_read=123.0)
    assert snap.ts_read == 123.0
    assert snap.indices == []
    assert snap.cycle.number is None
    assert snap.alerts.total is None
    assert snap.coverage.indices_count is None


def test_build_domain_snapshot_basic_cycle_and_indices():
    raw = {
        "indices": ["NIFTY", "BANKNIFTY"],
        "cycle": {"number": 42, "start": "2025-10-03T10:00:00Z", "duration": 1.25, "success_rate": 99.5},
        "alerts": {"total": 3, "severity_counts": {"warn": 2, "error": 1}},
        "resources": {"cpu_pct": 12.5, "memory_mb": 256.0},
    }
    snap = build_domain_snapshot(raw, ts_read=1000.0)
    assert snap.cycle.number == 42
    assert snap.cycle.last_duration_sec == 1.25
    assert snap.alerts.total == 3
    assert snap.alerts.severities["error"] == 1
    assert snap.resources.cpu_pct == 12.5
    assert snap.coverage.indices_count == 2
    assert set(snap.indices) == {"NIFTY", "BANKNIFTY"}


def test_build_domain_snapshot_loop_overrides():
    raw = {
        "cycle": 7,
        "loop": {"cycle": 8, "last_run": "2025-10-03T09:59:59Z", "last_duration": 0.5, "success_rate": 88.0},
    }
    snap = build_domain_snapshot(raw)
    assert snap.cycle.number == 8  # overridden by loop.cycle
    assert snap.cycle.last_duration_sec == 0.5
    assert snap.cycle.success_rate_pct == 88.0


def test_build_domain_snapshot_alerts_alt_names():
    raw = {
        "alerts": {"alerts_total": 5, "severity": {"warn": 4, "critical": 1}},
    }
    snap = build_domain_snapshot(raw)
    assert snap.alerts.total == 5
    assert snap.alerts.severities["critical"] == 1


def test_build_domain_snapshot_indices_dict_form():
    raw = {"indices": {"NIFTY": {}, "FINNIFTY": {}}, "resources": {"mem_mb": 512}}
    snap = build_domain_snapshot(raw)
    assert set(snap.indices) == {"NIFTY", "FINNIFTY"}
    # mem_mb accepted as memory_mb surrogate
    assert snap.resources.memory_mb == 512
