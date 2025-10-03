import time


def test_snapshot_builder_metrics(monkeypatch):
    # Ensure fresh module state
    monkeypatch.setenv('G6_SUMMARY_AGG_V2', '1')
    import importlib, scripts.summary.snapshot_builder as sb
    importlib.reload(sb)
    if hasattr(sb, '_reset_metrics_for_tests'):
        sb._reset_metrics_for_tests()

    # Force metric registration explicitly (defensive against lazy paths)
    if hasattr(sb, '_ensure_metrics'):
        sb._ensure_metrics()

    status = {
        'loop': {'cycle': 1, 'last_duration': 0.01},
        'interval': 60,
        'indices_detail': {
            'NIFTY': {'dq': {'score_percent': 99.0}, 'status': 'OK', 'age': 0.5},
        },
    }

    counter_obj, hist_obj = sb._get_internal_metric_objects()
    # Baseline ONLY from the counter's total sample (exclude *_created timestamp)
    baseline = 0
    if counter_obj is not None:
        for mf in counter_obj.collect():
            for s in mf.samples:
                # Prometheus client exposes <name>_total and <name>_created; we only want the incrementing total
                if s.name.endswith('_total'):
                    baseline = s.value

    for _ in range(3):
        sb.build_frame_snapshot(status)
        time.sleep(0.001)

    counter_obj, hist_obj = sb._get_internal_metric_objects()
    assert counter_obj is not None, "Counter not initialized"
    # Extract latest counter value
    counter_val = baseline
    for mf in counter_obj.collect():
        for s in mf.samples:
            if s.name.endswith('_total'):
                counter_val = s.value
    assert counter_val >= baseline + 3, f"expected counter to increase by >=3 (baseline={baseline}, now={counter_val})"

    assert hist_obj is not None, "Histogram not initialized"
    # Validate histogram count >= builds
    hist_count = 0
    for mf in hist_obj.collect():
        for s in mf.samples:
            if s.name.endswith('_count'):
                hist_count = s.value
    assert hist_count >= 3
