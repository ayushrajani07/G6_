from src.metrics import MetricsRegistry
from src.metrics.metrics import isolated_metrics_registry


def test_duplicate_registration_returns_same_collector():
    # Use isolated registry to avoid interference with global default collector set
    with isolated_metrics_registry() as reg:
    # First registration via maybe_register through group_registry already happened for panel_diff metrics.
        first = getattr(reg, 'panel_diff_writes', None)
        # Force a second registration attempt using internal helper.
        maybe = getattr(reg, '_maybe_register')
        again = maybe('panel_diff', 'panel_diff_writes', type(first), first._name, first._documentation, ['type'])  # type: ignore[attr-defined]
        assert again is first, "Expected duplicate registration to return original collector instance"
