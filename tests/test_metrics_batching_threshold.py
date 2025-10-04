import os, importlib, sys, time
from src.metrics import get_metrics, setup_metrics_server  # ensure metrics module loaded

def reload_emitter(threshold: int, interval: float = 60.0):
    # Set env for batcher enable + threshold
    os.environ['G6_METRICS_BATCH'] = '1'
    os.environ['G6_METRICS_BATCH_FLUSH_THRESHOLD'] = str(threshold)
    os.environ['G6_METRICS_BATCH_INTERVAL'] = str(interval)
    # Reload emitter to pick up new env
    if 'src.metrics.emitter' in sys.modules:
        importlib.reload(importlib.import_module('src.metrics.emitter'))
    else:
        importlib.import_module('src.metrics.emitter')
    from src.metrics.emitter import metric_batcher, batch_inc, pending_queue_size  # type: ignore
    return metric_batcher, batch_inc, pending_queue_size


def test_threshold_autoflush(monkeypatch):
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS','')
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS','')
    metric_batcher, batch_inc, pending_size = reload_emitter(threshold=3, interval=999.0)
    # Use a stable counter accessor from generated metrics; fall back to a simple one if absent
    from src.metrics.generated import m_api_calls_total_labels  # type: ignore
    # Queue 2 increments (below threshold)
    batch_inc(m_api_calls_total_labels, 'demo', 'ok')
    batch_inc(m_api_calls_total_labels, 'demo', 'ok')
    size_before = pending_size()
    assert size_before == 1  # merged key
    # Add third -> should trigger flush (threshold=3; but merged key so count still 1 until flush logic triggers)
    # To exercise threshold flush we need unique label tuples; vary label value
    batch_inc(m_api_calls_total_labels, 'demo2', 'ok')
    batch_inc(m_api_calls_total_labels, 'demo3', 'ok')
    # After adding enough distinct label tuples, threshold flush should have occurred (queue reset to 0)
    # Give a tiny sleep to allow flush outside lock
    time.sleep(0.05)
    assert pending_size() == 0
    # Subsequent increment should create queue again
    batch_inc(m_api_calls_total_labels, 'demo4', 'ok')
    assert pending_size() == 1

