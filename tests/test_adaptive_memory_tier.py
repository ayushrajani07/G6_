import os
import types

from src.orchestrator.adaptive_controller import evaluate_adaptive_controller

class _Counter:
    def __init__(self):
        self._value = types.SimpleNamespace(get=lambda: 0)
    def labels(self, **_):
        return self
    def inc(self, *_, **__):
        return self
    def set(self, *_, **__):
        return self
    def observe(self, *_, **__):
        return self

class _Gauge(_Counter):
    pass

class DummyMetrics:
    def __init__(self):
        self.cycle_sla_breach = _Counter()
        self.adaptive_controller_actions = _Counter()
        self.option_detail_mode = _Gauge()

class Ctx:
    __slots__ = ("metrics","_flags","index_params")
    def __init__(self):
        self.metrics = DummyMetrics()
        self._flags = {}
        self.index_params = {"NIFTY": {}}
    def set_flag(self, k,v):
        self._flags[k] = v
    def flag(self, k, default=None):
        return self._flags.get(k, default)


def test_memory_tier_demotes_without_sla_or_cardinality(monkeypatch):
    os.environ['G6_ADAPTIVE_CONTROLLER'] = '1'
    # Ensure thresholds
    os.environ['G6_ADAPTIVE_MIN_DETAIL_MODE'] = '2'
    os.environ['G6_ADAPTIVE_MAX_DETAIL_MODE'] = '0'
    ctx = Ctx()

    # Start healthy: memory tier good (0) first cycle -> remains mode 0
    ctx.set_flag('memory_tier', 0)
    evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)
    assert ctx.flag('option_detail_mode') == 0

    # Elevate memory tier to critical (2) -> expect demotion to 1 then 2 over subsequent cycles
    ctx.set_flag('memory_tier', 2)
    evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)
    assert ctx.flag('option_detail_mode') == 1
    # Maintain critical
    evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)
    assert ctx.flag('option_detail_mode') == 2

    # Recover memory tier to healthy -> accumulate recovery cycles (needs 5 by default) to promote back stepwise
    ctx.set_flag('memory_tier', 0)
    for _ in range(5):
        evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)
    # After 5 healthy cycles expect promotion from 2 -> 1
    assert ctx.flag('option_detail_mode') == 1
    for _ in range(5):
        evaluate_adaptive_controller(ctx, elapsed=10.0, interval=60.0)
    assert ctx.flag('option_detail_mode') == 0

    # Cleanup env
    for k in ['G6_ADAPTIVE_CONTROLLER','G6_ADAPTIVE_MIN_DETAIL_MODE','G6_ADAPTIVE_MAX_DETAIL_MODE']:
        os.environ.pop(k, None)
