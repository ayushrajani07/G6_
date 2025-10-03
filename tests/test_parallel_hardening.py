import os, time
import types
from types import SimpleNamespace

from src.orchestrator.cycle import run_cycle

class DummyProviders:
    def __init__(self, delays):
        self.delays = delays
        self.calls = []
    def get_index_data(self, index):  # minimal for fallback path
        self.calls.append(index)
        return 100.0, None
    def get_atm_strike(self, index):
        return 100.0

# Minimal CSV/Influx sinks
class DummySink:
    def write_overview_snapshot(self, *_, **__):
        return None

def make_ctx(indices):
    ctx = SimpleNamespace()
    ctx.index_params = {k: {"enable": True, "strikes_itm": 1, "strikes_otm":1, "expiries":["this_week"]} for k in indices}
    ctx.providers = DummyProviders({})
    ctx.csv_sink = DummySink()
    ctx.influx_sink = DummySink()
    ctx.metrics = types.SimpleNamespace()
    # attach only metrics attributes referenced
    from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry
    reg = CollectorRegistry()
    ctx.metrics.parallel_index_workers = Gauge('test_parallel_index_workers','test', registry=reg)
    ctx.metrics.parallel_index_failures = Counter('test_parallel_failures_total','test', ['index'], registry=reg)
    ctx.metrics.parallel_index_elapsed = Histogram('test_parallel_elapsed_seconds','test', buckets=[0.1,1,5], registry=reg)
    ctx.metrics.parallel_index_timeouts = Counter('test_parallel_timeouts_total','test',['index'], registry=reg)
    ctx.metrics.parallel_index_retries = Counter('test_parallel_retries_total','test',['index'], registry=reg)
    ctx.metrics.parallel_cycle_budget_skips = Counter('test_parallel_budget_skips_total','test', registry=reg)
    ctx.metrics.cycle_time_seconds = Histogram('test_cycle_time_seconds','test', buckets=[0.1,1,5], registry=reg)
    ctx.cycle_count = 0
    # minimal config used by _collect_single_index (greeks lookup)
    ctx.config = {}
    def flag(name, default=None):
        return default
    ctx.flag = flag
    return ctx


def test_parallel_timeout_and_budget(monkeypatch):
    ctx = make_ctx(['AAA','BBB','CCC'])
    # Force parallel
    monkeypatch.setenv('G6_PARALLEL_INDICES','1')
    monkeypatch.setenv('G6_PARALLEL_INDEX_WORKERS','3')
    monkeypatch.setenv('G6_CYCLE_INTERVAL','2')
    monkeypatch.setenv('G6_PARALLEL_INDEX_TIMEOUT_SEC','0.01')
    monkeypatch.setenv('G6_PARALLEL_CYCLE_BUDGET_FRACTION','0.1')
    start = time.time()
    run_cycle(ctx)  # type: ignore[arg-type]
    assert time.time() - start < 2.0  # respected interval bound


def test_parallel_retry(monkeypatch):
    # Simulate failure first then success on retry by monkeypatching _collect_single_index
    ctx = make_ctx(['IDX','X2'])  # need >1 index to enter parallel branch
    monkeypatch.setenv('G6_PARALLEL_INDICES','1')
    monkeypatch.setenv('G6_PARALLEL_INDEX_WORKERS','2')
    monkeypatch.setenv('G6_PARALLEL_INDEX_RETRY','1')
    calls = {'n':0}
    from src.orchestrator import cycle as cycle_mod
    orig = cycle_mod._collect_single_index
    def flaky(idx, params, _ctx):
        calls['n'] += 1
        if calls['n'] == 1:
            raise RuntimeError('boom')
        # success (no-op) on subsequent calls
        return None
    monkeypatch.setenv('G6_CYCLE_INTERVAL','5')
    monkeypatch.setenv('G6_PARALLEL_INDEX_TIMEOUT_SEC','1')
    cycle_mod._collect_single_index = flaky  # type: ignore
    run_cycle(ctx)  # type: ignore[arg-type]
    assert calls['n'] >= 2
    # restore original to avoid side-effects for other tests
    cycle_mod._collect_single_index = orig


def test_parallel_stagger(monkeypatch):
    ctx = make_ctx(['A','B'])
    monkeypatch.setenv('G6_PARALLEL_INDICES','1')
    monkeypatch.setenv('G6_PARALLEL_STAGGER_MS','50')
    monkeypatch.setenv('G6_PARALLEL_INDEX_WORKERS','2')
    monkeypatch.setenv('G6_CYCLE_INTERVAL','2')
    t0 = time.time()
    run_cycle(ctx)  # type: ignore[arg-type]
    # Should at least consume the stagger delay roughly
    assert time.time() - t0 >= 0.05
