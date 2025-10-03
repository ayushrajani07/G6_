import importlib, os

def test_alerts_dedup_metric_flag_off(monkeypatch):
    monkeypatch.setenv('G6_SUMMARY_AGG_V2', '0')
    import scripts.summary.snapshot_builder as sb
    importlib.reload(sb)
    if hasattr(sb, '_reset_metrics_for_tests'):
        sb._reset_metrics_for_tests()
    # Build frame (should not register metrics when flag off)
    sb.build_frame_snapshot({}, panels_dir=None)
    assert sb._get_alerts_dedup_metric() is None


def test_alerts_dedup_metric_flag_on(monkeypatch):
    monkeypatch.setenv('G6_SUMMARY_AGG_V2', '1')
    import scripts.summary.snapshot_builder as sb
    importlib.reload(sb)
    if hasattr(sb, '_reset_metrics_for_tests'):
        sb._reset_metrics_for_tests()
    # Build frame with duplicate alerts to trigger metric increment
    status = {'alerts': [
        {'time': '2025-09-27T10:00:00Z', 'level': 'INFO', 'component': 'A', 'message': 'm'},
        {'time': '2025-09-27T10:00:00Z', 'level': 'INFO', 'component': 'A', 'message': 'm'},
    ]}
    sb.build_frame_snapshot(status, panels_dir=None)
    m = sb._get_alerts_dedup_metric()
    # Counter should exist and have value >=1
    assert m is not None
    # Extract value
    val = 0
    for mf in m.collect():
        for s in mf.samples:
            if s.name.endswith('_total'):
                val = s.value
    assert val >= 1
