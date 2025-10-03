import os
import types
import pytest

from src.orchestrator.context import RuntimeContext
from src.orchestrator.adaptive_controller import evaluate_adaptive_controller


class _MetricsStub:
    """Minimal metrics stub exposing required counters/gauges for controller.

    We simulate a Prometheus-like counter with a _value.get() interface.
    """
    def __init__(self):
        class _Counter:
            def __init__(self):
                import threading
                self._value = types.SimpleNamespace(get=lambda: self.val)
                self.val = 0
            def inc(self, n: int = 1):
                self.val += n
        class _LabeledCounter:
            def __init__(self):
                self.series = []
            def labels(self, **lbls):  # type: ignore
                class _Inc:
                    def __init__(self, outer, labels):
                        self.outer = outer; self.labels = labels
                    def inc(self, n: int = 1):
                        self.outer.series.append((self.labels, n))
                return _Inc(self, lbls)
        class _Gauge:
            def __init__(self):
                self.values = {}
            def labels(self, **lbls):  # type: ignore
                class _Set:
                    def __init__(self, outer, labels):
                        self.outer = outer; self.labels = tuple(sorted(labels.items()))
                    def set(self, v):
                        self.outer.values[self.labels] = v
                return _Set(self, lbls)
        self.cycle_sla_breach = _Counter()
        self.adaptive_controller_actions = _LabeledCounter()
        self.option_detail_mode = _Gauge()


@pytest.fixture
def ctx():
    config = types.SimpleNamespace()
    context = RuntimeContext(config=config, metrics=_MetricsStub())
    # Provide single index to exercise gauge updates
    context.index_params = {"NIFTY": {"enable": True, "expiries": ["this_week"], "strikes_itm": 2, "strikes_otm": 2}}
    return context


def _run_controller(ctx, cycles: int, sla_breaches: bool = False):
    for _ in range(cycles):
        if sla_breaches:
            ctx.metrics.cycle_sla_breach.inc()
        evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)


def test_adaptive_controller_demotion_and_recovery(ctx, monkeypatch):
    """Controller should demote after configured SLA breach streak then promote after recovery cycles."""
    monkeypatch.setenv('G6_ADAPTIVE_CONTROLLER', '1')
    monkeypatch.setenv('G6_ADAPTIVE_SLA_BREACH_STREAK', '2')
    monkeypatch.setenv('G6_ADAPTIVE_RECOVERY_CYCLES', '3')
    monkeypatch.setenv('G6_ADAPTIVE_MIN_DETAIL_MODE', '2')
    monkeypatch.setenv('G6_ADAPTIVE_MAX_DETAIL_MODE', '0')

    # Initial mode should be 0
    evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)
    assert ctx.flag('option_detail_mode') == 0

    # Two consecutive breach cycles -> demote to 1
    _run_controller(ctx, cycles=2, sla_breaches=True)
    assert ctx.flag('option_detail_mode') == 1

    # Another two breach cycles -> demote to 2 (agg)
    _run_controller(ctx, cycles=2, sla_breaches=True)
    assert ctx.flag('option_detail_mode') == 2

    # Healthy cycles (no breaches) should eventually promote back toward 0
    _run_controller(ctx, cycles=3, sla_breaches=False)
    # After 3 healthy cycles: promote to 1
    assert ctx.flag('option_detail_mode') == 1
    _run_controller(ctx, cycles=3, sla_breaches=False)
    assert ctx.flag('option_detail_mode') == 0

    # Metrics assertions
    # At least two demotions and two promotions recorded
    demotes = [s for s in ctx.metrics.adaptive_controller_actions.series if s[0]['action']=='demote'] if ctx.metrics.adaptive_controller_actions.series else []  # type: ignore
    promotes = [s for s in ctx.metrics.adaptive_controller_actions.series if s[0]['action']=='promote'] if ctx.metrics.adaptive_controller_actions.series else []  # type: ignore
    assert len(demotes) >= 2
    assert len(promotes) >= 2
