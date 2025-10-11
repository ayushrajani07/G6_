import os
import types
import sys

class DummyGauge:
    def __init__(self):
        self.value = None
    def set(self, v):
        self.value = v

class DummyMetrics:
    pass

def test_memory_gauge_emitted(monkeypatch):
    # Ensure flag enabled
    monkeypatch.setenv('G6_PIPELINE_MEMORY_GAUGE','1')
    # Inject fake prometheus Gauge before import path executes gauge creation
    fake_prom = types.SimpleNamespace(Gauge=lambda *a, **k: DummyGauge())
    monkeypatch.setitem(sys.modules, 'prometheus_client', fake_prom)
    from src.collectors.modules import pipeline as pl
    metrics = DummyMetrics()
    # Run a minimal portion by invoking run_pipeline with empty inputs
    # Provide minimal params to avoid deep provider logic; we expect no indices processed
    result = pl.run_pipeline({}, providers=types.SimpleNamespace(get_atm_strike=lambda x: None), csv_sink=None, influx_sink=None, metrics=metrics)
    # After run, memory gauge should exist (if creation path executed) though may be None if import failed
    g = getattr(metrics, 'pipeline_memory_rss_mb', None)
    assert g is not None, 'Memory gauge not attached'
    # Value should be a float >= 0
    if hasattr(g, 'value'):
        assert g.value is None or g.value >= 0
