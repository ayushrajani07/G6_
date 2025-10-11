import os, types, sys

# We will monkeypatch scripts.bench_collectors.main to emit deterministic JSON quickly.
DUMMY_JSON = """{\n  \"config\": {},\n  \"legacy\": {\"p50_s\": 0.01, \"p95_s\": 0.02, \"mean_s\": 0.015},\n  \"pipeline\": {\"p50_s\": 0.011, \"p95_s\": 0.021, \"mean_s\": 0.016},\n  \"delta\": {\"p50_pct\": 10.0, \"p95_pct\": 5.0, \"mean_pct\": 6.67}\n}"""

class _FakeBenchModule:
    def main(self):  # pragma: no cover
        # Simulate bench_collectors JSON output to stdout (stdout captured by caller)
        print(DUMMY_JSON)

class _FakeGauge:
    def __init__(self, name, desc):
        self.name = name; self.desc = desc; self.value = None
    def set(self, v):
        self.value = v

class _FakeMetrics:  # acts as container for dynamic gauge attributes
    pass

# Patch prometheus_client.Gauge to return _FakeGauge so we can inspect values.
class _PrometheusModule(types.SimpleNamespace):
    def Gauge(self, name, desc):  # noqa: D401
        return _FakeGauge(name, desc)


def test_benchmark_cycle_integration(monkeypatch):
    # Force enable & immediate run
    monkeypatch.setenv('G6_BENCH_CYCLE', '1')
    monkeypatch.setenv('G6_BENCH_CYCLE_INTERVAL_SECONDS', '0')
    monkeypatch.setenv('G6_BENCH_CYCLE_CYCLES', '1')
    monkeypatch.setenv('G6_BENCH_CYCLE_WARMUP', '0')

    # Provide fake bench_collectors module
    fake_mod = _FakeBenchModule()
    monkeypatch.setitem(sys.modules, 'scripts.bench_collectors', fake_mod)

    # Provide fake prometheus_client
    prom = _PrometheusModule()
    monkeypatch.setitem(sys.modules, 'prometheus_client', prom)

    from src.collectors.modules.pipeline import _maybe_run_benchmark_cycle

    metrics = _FakeMetrics()
    _maybe_run_benchmark_cycle(metrics)

    # Assertions: gauges created with expected values
    assert hasattr(metrics, 'bench_legacy_p50_seconds')
    assert getattr(metrics, 'bench_legacy_p50_seconds').value == 0.01
    assert hasattr(metrics, 'bench_pipeline_p50_seconds')
    assert getattr(metrics, 'bench_pipeline_p50_seconds').value == 0.011
    assert hasattr(metrics, 'bench_delta_p50_pct')
    assert getattr(metrics, 'bench_delta_p50_pct').value == 10.0
    assert hasattr(metrics, 'bench_delta_mean_pct')
    assert getattr(metrics, 'bench_delta_mean_pct').value == 6.67
