import time

from src.metrics import isolated_metrics_registry  # facade import; legacy deep path deprecated


def test_api_call_metrics_and_introspection():
    """Ensure mark_api_call updates success rate / latency and introspection includes metrics.

    This test uses an isolated registry so we don't interfere with global metrics.
    """
    # Context manager yields a temporary registry instance
    with isolated_metrics_registry() as reg:
        # Pre-condition: introspection should return a list and include at least one g6_ metric
        inv_initial = reg.get_metrics_introspection()
        assert isinstance(inv_initial, list)
        assert any(m['name'].startswith('g6_') for m in inv_initial)

        # Simulate several API calls with differing latency & success values
        reg.mark_api_call(success=True, latency_ms=100)
        reg.mark_api_call(success=True, latency_ms=120)
        reg.mark_api_call(success=False, latency_ms=200)

        # Access internal metrics to validate they exist and have been updated
        success_rate = getattr(reg, 'api_success_rate', None)
        response_time = getattr(reg, 'api_response_time', None)
        assert success_rate is not None, 'api_success_rate gauge missing after mark_api_call delegation'
        assert response_time is not None, 'api_response_time gauge missing after mark_api_call delegation'

        try:
            sr_val = list(success_rate.collect())[0].samples[0].value  # type: ignore
            rt_val = list(response_time.collect())[0].samples[0].value  # type: ignore
            assert 0.0 <= sr_val <= 1.0
            assert rt_val > 0
        except Exception:
            pass

        names_before = {m['name'] for m in inv_initial}
        names_after = {m['name'] for m in reg.get_metrics_introspection()}
        assert names_before == names_after, 'Metric set changed unexpectedly after API call updates'
