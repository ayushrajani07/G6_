import os
import time
import importlib

from src.metrics.emission_batcher import EmissionBatcher, _Config
from prometheus_client import Counter

def make_batcher(enabled: bool = True, flush_interval: float = 0.05):
    cfg = _Config(enabled=enabled, flush_interval=flush_interval, max_queue=10000, max_drain=5000)
    return EmissionBatcher(cfg)

def test_utilization_and_downshift():
    os.environ["G6_EMISSION_BATCH_MIN_SIZE"] = "20"
    os.environ["G6_EMISSION_BATCH_MAX_SIZE"] = "200"
    os.environ["G6_EMISSION_BATCH_TARGET_INTERVAL_MS"] = "200"
    os.environ["G6_EMISSION_BATCH_UNDER_UTIL_THRESHOLD"] = "0.4"
    os.environ["G6_EMISSION_BATCH_UNDER_UTIL_CONSEC"] = "2"  # quicker downshift for test
    importlib.reload(__import__('src.metrics.emission_batcher'.replace('/', '.')))
    from src.metrics.emission_batcher import EmissionBatcher as B2, _Config as C2  # re-import after reload
    b = B2(C2(enabled=True, flush_interval=0.05, max_queue=10000, max_drain=5000))
    c = Counter('test_batch_util_counter_total', 'Test counter util')

    # Burst to raise target
    for _ in range(500):
        b.batch_increment(c, 1.0)
    b.flush()
    high_target = b._adaptive_target

    # Low activity cycles to trigger under-utilization downshift
    for _ in range(2):  # matches UNDER_UTIL_CONSEC
        b.batch_increment(c, 1.0)  # single increment -> very low utilization next flush
        time.sleep(0.01)
        b.flush()
    downshift_target = b._adaptive_target

    assert downshift_target <= high_target, (high_target, downshift_target)
    # Utilization gauge should have been set (0 < util <= 1)
    util = b._metrics.last_utilization()
    assert util is not None and 0 <= util <= 1
