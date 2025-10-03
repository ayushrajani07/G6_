import os
import time
import math
import types

from src.orchestrator.cardinality_guard import evaluate_cardinality_guard
from src.orchestrator.context import RuntimeContext
from src.metrics import setup_metrics_server  # facade import


def test_cardinality_guard_disable(monkeypatch):
    # Arrange
    os.environ['G6_CARDINALITY_MAX_SERIES'] = '10'
    metrics, _ = setup_metrics_server(port=9208, host='127.0.0.1', reset=True)
    ctx = RuntimeContext(config=types.SimpleNamespace())
    ctx.metrics = metrics

    # Monkeypatch estimator to a large number
    monkeypatch.setattr('src.orchestrator.cardinality_guard._estimate_series', lambda: 20000)

    # Act
    action, series = evaluate_cardinality_guard(ctx, force=True)

    # Assert
    assert action == 'disable'
    assert ctx.flag('per_option_metrics_disabled') is True
    assert series > 10


def test_cardinality_guard_reenable(monkeypatch):
    os.environ['G6_CARDINALITY_MAX_SERIES'] = '100'
    os.environ['G6_CARDINALITY_MIN_DISABLE_SECONDS'] = '0'
    os.environ['G6_CARDINALITY_REENABLE_FRACTION'] = '0.50'
    metrics, _ = setup_metrics_server(port=9209, host='127.0.0.1', reset=True)
    ctx = RuntimeContext(config=types.SimpleNamespace())
    ctx.metrics = metrics
    ctx.set_flag('per_option_metrics_disabled', True)
    ctx.set_flag('cardinality_last_toggle', time.time() - 5)

    # First evaluation still high keeps disabled
    monkeypatch.setattr('src.orchestrator.cardinality_guard._estimate_series', lambda: 120)
    action, _ = evaluate_cardinality_guard(ctx)
    assert action is None
    assert ctx.flag('per_option_metrics_disabled') is True

    # Now drop below re-enable threshold
    monkeypatch.setattr('src.orchestrator.cardinality_guard._estimate_series', lambda: 40)
    action, _ = evaluate_cardinality_guard(ctx)
    assert action == 'reenable'
    assert ctx.flag('per_option_metrics_disabled') is False


def test_sla_breach_counter(monkeypatch):
    os.environ['G6_CYCLE_INTERVAL'] = '2'
    os.environ['G6_CYCLE_SLA_FRACTION'] = '0.5'  # SLA budget = 1s
    metrics, _ = setup_metrics_server(port=9210, host='127.0.0.1', reset=True)
    from src.orchestrator.cycle import run_cycle

    # Deterministic elapsed simulation: monkeypatch time.time so second call advances by 1.25s
    real_time = time.time
    start_real = real_time()
    calls = {'n': 0}

    def fake_time():
        if calls['n'] == 0:
            calls['n'] += 1
            return start_real
        return start_real + 1.25

    monkeypatch.setattr('time.time', fake_time)

    class DictConfig(dict):
        def get(self, k, default=None):
            return super().get(k, default)

    class FastProvider:
        def get_index_data(self, idx):
            return (100.0, None)

    ctx = RuntimeContext(config=DictConfig({'greeks': {'enabled': False}}))
    ctx.metrics = metrics
    ctx.index_params = {'NIFTY': {'strikes_itm': 2, 'strikes_otm': 2}}
    ctx.providers = FastProvider()

    elapsed = run_cycle(ctx)  # type: ignore[arg-type]
    assert elapsed >= 1.2  # simulated elapsed
    assert hasattr(metrics, 'cycle_sla_breach')
    # Do not assert on internal last success time (not updated in this simplified path)
