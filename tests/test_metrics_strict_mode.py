import os
import importlib
import pytest

from src.metrics import isolated_metrics_registry  # facade import; legacy deep path deprecated


def test_strict_mode_raises(monkeypatch):
    # Force strict mode
    monkeypatch.setenv('G6_METRICS_STRICT_EXCEPTIONS', '1')

    # Create a bogus metric class that raises unexpected exception
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    with isolated_metrics_registry() as reg:
        # _maybe_register should re-raise RuntimeError in strict mode
        with pytest.raises(RuntimeError):
            reg._maybe_register('greeks', 'boom_metric', Boom, 'g6_boom_metric', 'Boom doc')  # type: ignore[attr-defined]


def test_non_strict_mode_swallows(monkeypatch):
    monkeypatch.delenv('G6_METRICS_STRICT_EXCEPTIONS', raising=False)

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("boom")

    with isolated_metrics_registry() as reg:
        # Should not raise
        reg._maybe_register('greeks', 'boom_metric', Boom, 'g6_boom_metric', 'Boom doc')  # type: ignore[attr-defined]
        assert not hasattr(reg, 'boom_metric')
