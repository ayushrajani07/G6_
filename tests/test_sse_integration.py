import time
from scripts.summary.sse_state import PanelStateStore


def test_sse_integration_panel_full_diff_severity_followup():
    store = PanelStateStore()
    # Initially heartbeat should indicate init
    hb0 = store.heartbeat()
    assert hb0['health'] == 'init'
    # Apply panel_full
    store.apply_panel_full({'indices_detail': {'NIFTY': {'status': 'ok'}}}, server_generation=1)
    snap1 = store.snapshot()
    status1, srv_gen1, ui_gen1, need_full1, counters1, sev_counts1, sev_state1, followups1 = snap1
    assert srv_gen1 == 1
    assert ui_gen1 == 1
    assert need_full1 is False
    assert counters1['panel_full'] == 1
    hb1 = store.heartbeat()
    assert hb1['health'] in ('ok','warn','init')  # recently updated
    # Apply severity counts/state
    store.update_severity_counts({'info': 2, 'warn': 1, 'critical': 0})
    store.update_severity_state('dq_alert', {'active': True, 'reasons': ['dq low']})
    # Apply panel_diff
    store.apply_panel_diff({'indices_detail': {'NIFTY': {'age': 5}}}, server_generation=1)
    # Add followup
    store.add_followup_alert({'time': 't', 'level': 'INFO', 'component': 'Follow-up dq', 'message': 'test'})
    status2, srv_gen2, ui_gen2, need_full2, counters2, sev_counts2, sev_state2, followups2 = store.snapshot()
    assert srv_gen2 == 1
    assert ui_gen2 >= 4  # full + severity counts + severity state + diff + followup
    # Depending on ordering, diff apply increments panel_diff_applied once
    assert counters2['panel_diff_applied'] == 1
    assert 'dq_alert' in sev_state2
    assert sev_counts2['info'] == 2
    assert len(followups2) == 1
    assert need_full2 is False
    # Heartbeat freshness
    hb2 = store.heartbeat(warn_after=0.0, stale_after=60.0)
    assert hb2['health'] in ('ok','warn')
    assert hb2['last_event_epoch'] is not None
    # Simulate staleness by manipulating internal timestamps (monkey patch)
    # Direct attribute access since test context; not part of public API but acceptable for integration test
    store._last_event_ts -= 120  # type: ignore[attr-defined]
    hb3 = store.heartbeat(warn_after=5.0, stale_after=30.0)
    assert hb3['health'] == 'stale'
