import math
from src.metrics import MetricsRegistry, isolated_metrics_registry  # facade import
from prometheus_client import REGISTRY


def test_mark_api_call_success_and_failure():
    # Isolate Prometheus default registry to avoid duplicate metric registration across tests
    with isolated_metrics_registry():
        # Defensive cleanup: remove any leftover g6_* collectors registered earlier in the session
        try:
            current = dict(getattr(REGISTRY, '_names_to_collectors', {}))  # type: ignore[attr-defined]
            for name, collector in list(current.items()):
                if isinstance(name, str) and name.startswith('g6_'):
                    try:
                        REGISTRY.unregister(collector)  # type: ignore[arg-type]
                    except Exception:
                        pass
        except Exception:
            pass
        m = MetricsRegistry()
    # Initial state
        assert m._api_calls == 0
        assert m._api_failures == 0

    # Simulate successful call
        m.mark_api_call(success=True, latency_ms=100)
        assert m._api_calls == 1
        assert m._api_failures == 0
    # Gauge updated (EMA should equal first sample)
        assert m.api_response_time._value.get() == 100  # type: ignore

    # Simulate failed call with different latency
        m.mark_api_call(success=False, latency_ms=200)
        assert m._api_calls == 2
        assert m._api_failures == 1

    # Success rate gauge ( (2-1)/2 * 100 ) = 50
        assert math.isclose(m.api_success_rate._value.get(), 50.0, rel_tol=1e-6)  # type: ignore

    # EMA should now be 0.3*200 + 0.7*100 = 130
        assert math.isclose(m.api_response_time._value.get(), 130.0, rel_tol=1e-6)  # type: ignore

    # Histogram should have observed two samples; access internal sum/count
        hist_samples = None
        for metric in m.api_response_latency.collect():  # type: ignore
            for sample in metric.samples:
                if sample.name.endswith('_count'):
                    if sample.value == 2:
                        hist_samples = sample.value
                if sample.name.endswith('_sum'):
                    # Sum should be 100 + 200 = 300
                    assert math.isclose(sample.value, 300.0, rel_tol=1e-6)
        assert hist_samples == 2

    # Another failure without latency (should not change latency EMA/hist)
        m.mark_api_call(success=False, latency_ms=None)
        assert m._api_calls == 3
        assert m._api_failures == 2
        # Success rate now ( (3-2)/3 * 100 ) = 33.333...
        assert math.isclose(m.api_success_rate._value.get(), (1/3)*100.0, rel_tol=1e-6)  # type: ignore
        # EMA unchanged
        assert math.isclose(m.api_response_time._value.get(), 130.0, rel_tol=1e-6)  # type: ignore
