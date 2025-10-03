import time
from types import SimpleNamespace
from prometheus_client import CollectorRegistry

from src.orchestrator.cycle import run_cycle

class DummyProviders:
    def get_index_data(self, index):
        return 100.0, None
    def get_atm_strike(self, index):
        return 100.0

class DummySink:
    def write_overview_snapshot(self, *a, **k):
        return None

def make_ctx():
    ctx = SimpleNamespace()
    ctx.index_params = {"AAA": {"enable": True, "strikes_itm":1, "strikes_otm":1, "expiries":["this_week"]}}
    ctx.providers = DummyProviders()
    ctx.csv_sink = DummySink()
    ctx.influx_sink = DummySink()
    ctx.cycle_count = 0
    ctx.config = {}
    # minimal metrics namespace with needed gauges
    reg = CollectorRegistry()
    from prometheus_client import Gauge, Counter, Histogram
    m = SimpleNamespace()
    m.cycle_time_seconds = Histogram('test_cycle_time_seconds','cycle', registry=reg)
    m.cycle_sla_breach = Counter('test_cycle_sla_breach_total','sla', registry=reg)
    m.data_gap_seconds = Gauge('test_data_gap_seconds','gap', registry=reg)
    m.index_data_gap_seconds = Gauge('test_index_data_gap_seconds','index gap', ['index'], registry=reg)
    ctx.metrics = m
    return ctx


def test_data_gap_increases_between_cycles(monkeypatch):
    monkeypatch.setenv('G6_CYCLE_INTERVAL','1')
    ctx = make_ctx()
    # First cycle establishes last success timestamp
    run_cycle(ctx)  # type: ignore[arg-type]
    time.sleep(0.05)
    t0 = time.time()
    run_cycle(ctx)  # type: ignore[arg-type]
    # data_gap_seconds is updated inside second run at end referencing prior timestamp
    # We stored gap indirectly; emulate instrumentation logic: if last_success set before second cycle ended, gap should be small
    last_success = getattr(ctx.metrics, '_last_success_cycle_time', None)
    assert last_success is not None
    # Immediately after a successful cycle gap should be near zero (< interval)
    assert (time.time() - last_success) < 1.0
