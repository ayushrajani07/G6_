import os, importlib, time
from src.orchestrator.context import RuntimeContext

class DummyMetrics: pass

class DummyProviders: pass

def _mk_ctx():
    return RuntimeContext(config={}, index_params={'NIFTY': {'enable': False}}, providers=DummyProviders(), csv_sink=None, influx_sink=None, metrics=DummyMetrics())

def test_cycle_interval_inline_comment(monkeypatch):
    # Include inline comment which previously caused ValueError
    monkeypatch.setenv('G6_CYCLE_INTERVAL', '30   # seconds per cycle')
    from src.orchestrator import cycle as cycle_mod
    # Re-import not strictly necessary due to helper being runtime read, but safe.
    importlib.reload(cycle_mod)
    ctx = _mk_ctx()
    # Run once with parallel disabled path
    monkeypatch.delenv('G6_PARALLEL_INDICES', raising=False)
    start = time.time()
    elapsed = cycle_mod.run_cycle(ctx)
    # Ensure it returns quickly (providers disabled path) and did not raise
    assert elapsed >= 0.0


def test_parallel_interval_inline_comment(monkeypatch):
    monkeypatch.setenv('G6_CYCLE_INTERVAL', '45 # comment here')
    monkeypatch.setenv('G6_PARALLEL_INDICES', '1')
    # Provide at least two indices to trigger parallel branch
    ctx = RuntimeContext(config={}, index_params={'A': {'enable': False}, 'B': {'enable': False}}, providers=DummyProviders(), csv_sink=None, influx_sink=None, metrics=DummyMetrics())
    from src.orchestrator import cycle as cycle_mod
    importlib.reload(cycle_mod)
    elapsed = cycle_mod.run_cycle(ctx)
    assert elapsed >= 0.0
