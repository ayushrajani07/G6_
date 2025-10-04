import os
import time
from src.metrics.emission_batcher import EmissionBatcher, _Config
from prometheus_client import Counter


def test_batcher_flush_basic(monkeypatch):
    # Ensure enabled config
    cfg = _Config(enabled=True, flush_interval=0.2, max_queue=1000, max_drain=1000)
    c = Counter('test_batch_counter_total', 'test counter')
    b = EmissionBatcher(cfg)
    try:
        for _ in range(10):
            b.batch_increment(c, value=1)
        # Force flush
        b.flush()
        # Counter should have value 10
        # Prom client stores samples; access _value for simplicity
        assert c._value.get() == 10  # type: ignore[attr-defined]
    finally:
        b.shutdown()


def test_batcher_queue_overflow(monkeypatch):
    cfg = _Config(enabled=True, flush_interval=1.0, max_queue=2, max_drain=10)
    c = Counter('test_batch_overflow_counter_total', 'test counter overflow', ['k'])
    b = EmissionBatcher(cfg)
    try:
        b.batch_increment(c, value=1, labels={'k':'a'})
        b.batch_increment(c, value=1, labels={'k':'b'})
        # Third distinct key should be dropped
        b.batch_increment(c, value=1, labels={'k':'c'})
        b.flush()
        # Only first two applied
        assert c.labels(k='a')._value.get() == 1  # type: ignore[attr-defined]
        assert c.labels(k='b')._value.get() == 1  # type: ignore[attr-defined]
    finally:
        b.shutdown()
