import pytest

from src.metrics import isolated_metrics_registry  # facade import; legacy deep path deprecated

@pytest.mark.parametrize("metric_attr, expected_prefix", [
    ("option_detail_band_rejections", "g6_option_detail_band_rejections"),
    ("expiry_rewritten_total", "g6_expiry_rewritten"),  # allow client internal name without _total
    ("provider_failover", "g6_provider_failover"),      # allow client internal name without _total
])
def test_placeholder_metrics_present_early(metric_attr, expected_prefix):
    """Placeholders must be registered immediately upon MetricsRegistry creation.

    Regression guard: Earlier refactor moved placeholder init ahead/behind core registration
    causing band rejection counter absence and multiple downstream test failures.
    This test defensively asserts critical always-on metrics exist without any
    additional feature flag toggling or later group registration passes.
    """
    with isolated_metrics_registry() as reg:
        # Access attribute presence
        assert hasattr(reg, metric_attr), f"Placeholder metric {metric_attr} missing early"
        # Validate underlying prometheus collector name if possible
        metric = getattr(reg, metric_attr)
        name = getattr(metric, "_name", None)
        assert isinstance(name, str) and name.startswith(expected_prefix), (
            f"Expected collector name starting with {expected_prefix} got {name} for {metric_attr}"
        )
