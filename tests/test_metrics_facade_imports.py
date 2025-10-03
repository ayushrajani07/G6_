import importlib


def test_facade_vs_legacy_get_metrics_identity():
    facade_mod = importlib.import_module('src.metrics')
    legacy_mod = importlib.import_module('src.metrics.metrics')
    gm_facade = getattr(facade_mod, 'get_metrics')
    gm_legacy = getattr(legacy_mod, 'get_metrics')
    assert gm_facade() is gm_legacy(), "Facade get_metrics should return same singleton instance as legacy path"


def test_facade_register_build_info_available():
    facade_mod = importlib.import_module('src.metrics')
    rbi = getattr(facade_mod, 'register_build_info')
    # Should be callable with None (no-op) and not raise
    rbi(None, version="test")


def test_isolated_metrics_registry_context_manager():
    facade_mod = importlib.import_module('src.metrics')
    isolated_cm = getattr(facade_mod, 'isolated_metrics_registry')
    with isolated_cm() as reg:
        # Registry should expose at least one known metric attribute after increment/creation
        reg.options_processed_total.inc()  # created in metrics monolith
        assert hasattr(reg, 'options_processed_total')
