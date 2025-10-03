from __future__ import annotations

from scripts.summary.sse_state import PanelStateStore

def test_severity_counts_and_state_and_followups():
    store = PanelStateStore()
    # Baseline full apply to clear need_full
    store.apply_panel_full({"cycle": 1}, server_generation=10)
    # Update severity counts
    store.update_severity_counts({"info": 2, "warn": 1, "critical": 0})
    # Update severity state
    store.update_severity_state("momentum_alert", {
        "active": True,
        "previous_active": False,
        "last_change_cycle": 15,
        "resolved": False,
        "resolved_count": 3,
        "reasons": ["threshold_exceeded"],
        "alert": {"message": "Momentum threshold exceeded", "severity": "WARN"}
    })
    # Add followup alert
    store.add_followup_alert({
        "time": "2025-10-01T12:00:00Z",
        "level": "WARN",
        "component": "Follow-up momentum_alert NIFTY",
        "message": "Momentum still elevated"
    })
    status, srv_gen, ui_gen, need_full, counters, sev_counts, sev_state, followups = store.snapshot()
    assert sev_counts["info"] == 2
    assert sev_counts["warn"] == 1
    assert "momentum_alert" in sev_state
    assert isinstance(followups, list) and len(followups) == 1
    assert followups[0]["level"] == "WARN"
    assert need_full is False

if __name__ == "__main__":  # pragma: no cover
    import pytest
    pytest.main([__file__])
