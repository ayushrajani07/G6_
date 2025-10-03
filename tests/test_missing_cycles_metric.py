import time
from prometheus_client import Counter, CollectorRegistry
from src.orchestrator.cycle import run_cycle
from src.metrics import isolated_metrics_registry  # facade import
from src.orchestrator.context import RuntimeContext


class _StubMetrics:
    """Minimal metrics stub exposing only missing_cycles Counter.

    Using an isolated CollectorRegistry prevents duplicated timeseries errors
    stemming from global registry reuse across unrelated tests.
    """
    def __init__(self):
        self._registry = CollectorRegistry()
        self.missing_cycles = Counter('g6_missing_cycles_total', 'Detected missing cycles (scheduler gaps)', registry=self._registry)
        # Minimal placeholders used by other code paths (no-ops)
        class _NoOpGauge:
            def set(self, *_a, **_kw):
                return None
        class _NoOpSummary:
            def observe(self, *_a, **_kw):
                return None
        class _NoOpGauge2:
            def set(self, *_a, **_kw):
                return None
        # Additional placeholders referenced by other code paths to avoid attribute errors
        self.memory_depth_scale = _NoOpGauge2()
        self.avg_cycle_time = _NoOpGauge2()
        class _NoOpCounter:
            def inc(self, *_a, **_kw):
                return None
        self.memory_pressure_level = _NoOpGauge()
        self.memory_pressure_seconds_in_level = _NoOpGauge()
        self.memory_pressure_downgrade_pending = _NoOpGauge()
        self.collection_cycles = _NoOpCounter()
        self.collection_duration = _NoOpSummary()

    def collect_value(self) -> float:
        # Direct access to internal counter value (simpler than iterating registry samples)
        try:
            return float(self.missing_cycles._value.get())  # type: ignore[attr-defined]
        except Exception:
            return 0.0


def _make_ctx():
    metrics = _StubMetrics()
    ctx = RuntimeContext(config={}, metrics=metrics)
    ctx.index_params = {}
    return ctx


def test_missing_cycles_metric(monkeypatch):
    """Unified test covering default factor behavior and custom factor adjustment without recreating registries."""
    with isolated_metrics_registry():
        ctx = _make_ctx()
        monkeypatch.setenv('G6_CYCLE_INTERVAL', '60')
        base_time = time.time()
        setattr(ctx, '_last_cycle_start', base_time)
        monkeypatch.setattr(time, 'time', lambda: base_time + 5)
        run_cycle(ctx)  # type: ignore[arg-type]
        start0 = getattr(ctx, '_last_cycle_start')
        def counter_value():
            return ctx.metrics.collect_value()  # type: ignore[attr-defined]
        monkeypatch.setattr(time, 'time', lambda: start0 + 30)
        run_cycle(ctx)  # type: ignore[arg-type]
        assert counter_value() == 0
        start1 = getattr(ctx, '_last_cycle_start')
        monkeypatch.setattr(time, 'time', lambda: start1 + 121)
        run_cycle(ctx)  # type: ignore[arg-type]
        assert counter_value() == 1
        start2 = getattr(ctx, '_last_cycle_start')
        monkeypatch.setattr(time, 'time', lambda: start2 + 130)
        run_cycle(ctx)  # type: ignore[arg-type]
        assert counter_value() == 2
        # Phase 2: Custom factor (1.2)
        monkeypatch.setenv('G6_MISSING_CYCLE_FACTOR', '1.2')
        new_base = start2 + 5
        setattr(ctx, '_last_cycle_start', new_base)
        monkeypatch.setattr(time, 'time', lambda: new_base + 50)
        run_cycle(ctx)  # type: ignore[arg-type]
        assert counter_value() == 2  # below threshold
        after1 = getattr(ctx, '_last_cycle_start')
        monkeypatch.setattr(time, 'time', lambda: after1 + 72)
        run_cycle(ctx)  # type: ignore[arg-type]
        assert counter_value() == 3
        # Phase 3: Huge factor -> no increment
        monkeypatch.setenv('G6_MISSING_CYCLE_FACTOR', '5000')
        after2 = getattr(ctx, '_last_cycle_start')
        monkeypatch.setattr(time, 'time', lambda: after2 + 300)
        run_cycle(ctx)  # type: ignore[arg-type]
        assert counter_value() == 3
