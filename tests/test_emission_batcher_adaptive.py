import time
import os
import importlib

from src.metrics.emission_batcher import EmissionBatcher, _Config


def make_batcher(enabled: bool = True, flush_interval: float = 0.05):
    cfg = _Config(enabled=enabled, flush_interval=flush_interval, max_queue=10000, max_drain=5000)
    return EmissionBatcher(cfg)


def test_adaptive_increases_with_rate():
    os.environ.setdefault("G6_EMISSION_BATCH_TARGET_INTERVAL_MS", "200")
    b = make_batcher()
    # Warm some increments at low rate
    from prometheus_client import Counter
    c = Counter('test_adaptive_counter_total', 'Test adaptive counter')

    for _ in range(20):
        b.batch_increment(c, 1.0)
    b.flush()
    low_target = b._adaptive_target

    # Simulate higher rate bursts
    for _ in range(500):
        b.batch_increment(c, 1.0)
    b.flush()
    high_target = b._adaptive_target

    assert high_target >= low_target, (low_target, high_target)


def test_adaptive_clamped_between_min_max():
    os.environ["G6_EMISSION_BATCH_MIN_SIZE"] = "10"
    os.environ["G6_EMISSION_BATCH_MAX_SIZE"] = "200"
    # Re-import to ensure env read (not strictly necessary for test if values read in __init__ only)
    importlib.reload(__import__('src.metrics.emission_batcher'.replace('/', '.')))
    b = make_batcher()
    from prometheus_client import Counter
    c = Counter('test_adaptive_counter2_total', 'Test adaptive counter 2')

    for _ in range(5):
        b.batch_increment(c, 1.0)
    b.flush()
    assert b._adaptive_target >= 10

    for _ in range(2000):
        b.batch_increment(c, 1.0)
    b.flush()
    assert b._adaptive_target <= 200


def test_batcher_disabled_direct_passthrough():
    b = make_batcher(enabled=False)
    from prometheus_client import Counter
    c = Counter('test_adaptive_counter3_total', 'Test adaptive counter 3')
    before = c._value.get()  # type: ignore[attr-defined]
    for _ in range(5):
        b.batch_increment(c, 1.0)
    after = c._value.get()  # type: ignore[attr-defined]
    assert after - before == 5
