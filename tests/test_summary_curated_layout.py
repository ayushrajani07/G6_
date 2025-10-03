import os
import json
from src.summary.curated_layout import CuratedLayout, collect_state, SummaryState

SAMPLE_STATUS = {
    "run_id": "abcdef123",
    "version": "1.2.3",
    "market": {"status": "OPEN"},
    "loop": {"cycle": 42, "last_duration": 0.72, "p95_ms": 880, "interval": 60, "next_run_in_sec": 59.3, "missed_cycles": 1, "on_time_percent": 98.7},
    "sla": {"target_ms": 900, "breach_streak": 0},
    "indices_detail": {
        "NIFTY": {"dq": {"score_percent": 92}, "rows": 1820, "success_percent": 97, "pct_change": 0.84},
        "BANKNIFTY": {"dq": {"score_percent": 90}, "rows": 1490, "success_percent": 95, "pct_change": 0.42},
        "FINNIFTY": {"dq": {"score_percent": 94}, "rows": 880, "success_percent": 98, "pct_change": -0.12},
    },
    "provider": {"latency_p95_ms": 420, "error_percent": 0.6, "circuit_breaker_state": "closed"},
    "influx": {"write_p95_ms": 55, "queue": 120, "dropped": 0},
    "dq": {"score_percent": 92, "warn_threshold": 85, "error_threshold": 70},
    "cardinality": {"active_series": 13200, "budget": 20000, "disabled_events": 0, "atm_window": 6, "emit_rate_per_sec": 240},
    "resources": {"rss_mb": 452, "cpu_percent": 34, "mem_tier": "T2", "headroom_percent": 18, "rollback_in": 3},
    "alerts_meta": {"severity_counts": {"info": 3, "warn": 1, "critical": 0}, "active_types": 2, "resolved_recent": 5},
    "adaptive": {"detail_mode": "band", "demote_in": 2, "promote_in": 4, "reasons": ["sla_streak(2)"]},
    "vol_surface": {"coverage_pct": 78, "interp_fraction": 12, "atm_iv": 14.8},
    "risk_agg": {"delta_notional": 3_200_000, "vega_notional": 1_100_000, "drift_pct": 1.2},
    "followups_recent": [{"type": "interp_guard", "streak": 4}],
    "heartbeat": {"last_event_seconds": 2, "metrics_age_seconds": 1, "latency_p95_spark": "▂▄█▆"},
}


def test_curated_layout_basic_render():
    st = collect_state(SAMPLE_STATUS)
    layout = CuratedLayout()
    out = layout.render(st, term_cols=100, term_rows=28)
    # Must contain mandatory sections
    assert "RUN" in out and "CYC" in out and "IDX" in out
    # Should include analytics in wide mode
    assert "AN vol_cov" in out


def test_curated_layout_prunes_analytics_first():
    st = collect_state(SAMPLE_STATUS)
    layout = CuratedLayout()
    out_full = layout.render(st, term_cols=100, term_rows=15)
    # With more space analytics present
    assert "AN vol_cov" in out_full
    out_tight = layout.render(st, term_cols=100, term_rows=8)
    # Very tight height should drop analytics or shrink
    assert ("AN vol_cov" not in out_tight) or (out_tight.count("\n") < out_full.count("\n"))


def test_curated_layout_shrinks_before_drop():
    st = collect_state(SAMPLE_STATUS)
    layout = CuratedLayout()
    out_tight = layout.render(st, term_cols=100, term_rows=9)
    # In tight mode cycle block should be shrunk to single line representation
    cycle_lines = [l for l in out_tight.splitlines() if l.startswith("CYC ")]
    assert cycle_lines, "Cycle line missing"
    # Expect the compact variant containing '/' between last and p95
    assert any("/" in l for l in cycle_lines)


def test_curated_layout_preserves_critical_alerts():
    critical_status = json.loads(json.dumps(SAMPLE_STATUS))
    critical_status["alerts_meta"]["severity_counts"]["critical"] = 2
    st = collect_state(critical_status)
    layout = CuratedLayout()
    out = layout.render(st, term_cols=100, term_rows=9)
    # Ensure ALERTS block not dropped
    assert any(l.startswith("ALERTS") or l.startswith("ALRT") for l in out.splitlines())


def test_curated_layout_hides_empty_blocks(monkeypatch):
    """When G6_SUMMARY_HIDE_EMPTY_BLOCKS enabled and analytics/followups empty they are suppressed."""
    empty_status = {
        "run_id": "zzz123",
        "version": "0.0.1",
        "market": {"status": "OPEN"},
        "loop": {"cycle": 1, "last_duration": 0.5, "p95_ms": 600, "interval": 60, "next_run_in_sec": 59.5},
        "sla": {"target_ms": 900, "breach_streak": 0},
        "indices_detail": {},
        "provider": {},
        "influx": {},
        "dq": {},
        "cardinality": {},
        "resources": {},
        "alerts_meta": {"severity_counts": {"info":0,"warn":0,"critical":0}},
        # intentionally omit vol_surface / risk_agg / followups_recent
    }
    monkeypatch.setenv('G6_SUMMARY_CURATED_MODE','1')
    monkeypatch.setenv('G6_SUMMARY_HIDE_EMPTY_BLOCKS','1')
    st = collect_state(empty_status)
    layout = CuratedLayout()
    out = layout.render(st, term_cols=100, term_rows=20)
    # Should not contain AN vol_cov or FUP none when hidden
    assert 'AN vol_cov' not in out
    assert not any(l.startswith('FUP') for l in out.splitlines())

    # When flag disabled, blocks appear (analytics line shows unknowns, followups none)
    monkeypatch.delenv('G6_SUMMARY_HIDE_EMPTY_BLOCKS', raising=False)
    st2 = collect_state(empty_status)
    out2 = layout.render(st2, term_cols=100, term_rows=20)
    assert any(l.startswith('FUP') for l in out2.splitlines())
