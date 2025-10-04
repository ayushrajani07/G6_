import os, time, importlib, sys
import statistics as stats
import pytest

# Optional perf test; enable with G6_ENABLE_PERF_TESTS=1
pytestmark = pytest.mark.skipif(os.getenv('G6_ENABLE_PERF_TESTS','') == '', reason='Set G6_ENABLE_PERF_TESTS=1 to run performance micro-benchmarks')

ITER = int(os.getenv('G6_BATCH_PERF_ITER', '20000'))
LABELS = [('ep1','ok'), ('ep2','ok'), ('ep3','err')]


def _reload_emitter(batch: bool, threshold: int = 0):
    # Reset env to force fresh batcher
    os.environ['G6_METRICS_BATCH'] = '1' if batch else '0'
    os.environ['G6_METRICS_BATCH_INTERVAL'] = '5.0'
    os.environ['G6_METRICS_BATCH_FLUSH_THRESHOLD'] = str(threshold)
    if 'src.metrics.emitter' in sys.modules:
        importlib.reload(importlib.import_module('src.metrics.emitter'))
    else:
        importlib.import_module('src.metrics.emitter')
    from src.metrics.emitter import batch_inc, metric_batcher, flush_now  # type: ignore
    return batch_inc, metric_batcher, flush_now


def _baseline_counter_accessor():
    from src.metrics.generated import m_api_calls_total_labels  # type: ignore
    return m_api_calls_total_labels


def _run_direct(accessor):
    # Disable batching path by calling accessor directly
    start = time.perf_counter()
    for i in range(ITER):
        lbl = accessor(*LABELS[i % len(LABELS)])
        lbl.inc()
    return time.perf_counter() - start


def _run_batched(accessor, threshold: int):
    batch_inc, _mb, flush_now = _reload_emitter(batch=True, threshold=threshold)
    start = time.perf_counter()
    for i in range(ITER):
        ep, res = LABELS[i % len(LABELS)]
        batch_inc(accessor, ep, res)
    # Ensure final flush
    flush_now()
    return time.perf_counter() - start


def test_batching_perf_smoke():
    accessor = _baseline_counter_accessor()
    # Warm metric objects outside timing
    for l in LABELS:
        accessor(*l)
    direct = _run_direct(accessor)
    batched = _run_batched(accessor, threshold=0)
    # Adaptive threshold variant
    batched_thresh = _run_batched(accessor, threshold=5)
    # Provide basic assertions (batched should not be catastrophically slower)
    # In low iteration counts overhead may dominate; allow generous factor.
    assert batched < direct * 2.5, f"Batched path too slow: direct={direct:.4f}s batched={batched:.4f}s"
    assert batched_thresh < direct * 2.5, f"Threshold batched path too slow: direct={direct:.4f}s thresh={batched_thresh:.4f}s"
    # Log comparative stats
    ratios = {
        'direct_s': direct,
        'batched_s': batched,
        'batched_threshold_s': batched_thresh,
        'speedup_vs_direct': direct / batched if batched else float('inf'),
        'speedup_threshold_vs_direct': direct / batched_thresh if batched_thresh else float('inf'),
    }
    print('BATCH_PERF', ratios)
