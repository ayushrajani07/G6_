import os, types, sys

DUMMY_JSON = """{\n  \"config\": {},\n  \"legacy\": {\"p50_s\": 0.01, \"p95_s\": 0.02, \"mean_s\": 0.015},\n  \"pipeline\": {\"p50_s\": 0.012, \"p95_s\": 0.025, \"mean_s\": 0.017},\n  \"delta\": {\"p50_pct\": 20.0, \"p95_pct\": 25.0, \"mean_pct\": 13.33}\n}"""

class _FakeBenchModule:
    def main(self):  # pragma: no cover
        print(DUMMY_JSON)

class _FakeGauge:
    def __init__(self, name, desc):
        self.name = name; self.desc = desc; self.value = None
    def set(self, v):
        self.value = v

class _FakeMetrics: pass

class _PrometheusModule(types.SimpleNamespace):
    def Gauge(self, name, desc):  # noqa: D401
        return _FakeGauge(name, desc)


def test_bench_threshold_gauge(monkeypatch):
    monkeypatch.setenv('G6_BENCH_CYCLE', '1')
    monkeypatch.setenv('G6_BENCH_CYCLE_INTERVAL_SECONDS', '0')
    monkeypatch.setenv('G6_BENCH_CYCLE_CYCLES', '1')
    monkeypatch.setenv('G6_BENCH_CYCLE_WARMUP', '0')
    monkeypatch.setenv('G6_BENCH_P95_ALERT_THRESHOLD', '22.5')

    fake_mod = _FakeBenchModule()
    prom = _PrometheusModule()
    monkeypatch.setitem(sys.modules, 'scripts.bench_collectors', fake_mod)
    monkeypatch.setitem(sys.modules, 'prometheus_client', prom)

    from src.collectors.modules.pipeline import _maybe_run_benchmark_cycle
    metrics = _FakeMetrics()
    _maybe_run_benchmark_cycle(metrics)

    thr = getattr(metrics, 'bench_p95_regression_threshold_pct')
    # Accept either direct value or early-initialized gauge
    assert getattr(thr, 'value', 22.5) == 22.5
    # Ensure p95 delta gauge exists too
    assert getattr(metrics, 'bench_delta_p95_pct').value == 25.0
    # Validate alert condition would trigger (delta > threshold)
    assert getattr(metrics, 'bench_delta_p95_pct').value > thr.value
