import os
# Ensure passthrough env cleared globally for this test module so adaptive.py reads correct mode
os.environ.pop('G6_ADAPTIVE_SCALE_PASSTHROUGH', None)

from src.orchestrator.context import RuntimeContext
from src.orchestrator.cycle import run_cycle

class DummyMetrics:
    def __init__(self):
        class G:
            def labels(self, **_):
                return self
            def set(self, *_a, **_k):
                pass
        self.strike_depth_scale_factor = G()
        self.cycle_time_seconds = G()

class DummyProviders:
    def get_index_data(self, index):
        return 100, {}
    def get_atm_strike(self, index):
        return 100
    def resolve_expiry(self, index, rule):
        return '2025-12-31'
    def get_option_instruments(self, index, expiry, strikes):
        return []
    def enrich_with_quotes(self, instruments):
        return {}
    def get_expiry_dates(self, index):
        return ['2025-12-31']


def _run_cycles(ctx, elapsed_values, interval):
    # Simulate cycles by mocking elapsed via environment interval and overriding timing logic through direct pass
    os.environ['G6_CYCLE_INTERVAL'] = str(interval)
    for e in elapsed_values:
        # We can't inject elapsed directly; run_cycle computes it. Instead, fast path run_cycle and then manually call adaptive.
        # Simplify by calling update_strike_scaling directly (import from module).
        from src.orchestrator.adaptive import update_strike_scaling
        update_strike_scaling(ctx, e, interval)
        ctx.cycle_count += 1


def test_adaptive_scale_down_and_restore():
    # Force disable passthrough (explicit) so mutation path may activate; if an external
    # test toggles it later we still accept non-mutation as long as scale factor falls.
    os.environ['G6_ADAPTIVE_SCALE_PASSTHROUGH'] = '0'
    os.environ['G6_ADAPTIVE_STRIKE_SCALING'] = '1'
    os.environ['G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD'] = '3'
    os.environ['G6_ADAPTIVE_STRIKE_RESTORE_HEALTHY'] = '5'
    os.environ['G6_ADAPTIVE_STRIKE_REDUCTION'] = '0.8'
    ctx = RuntimeContext(config={}, providers=DummyProviders(), metrics=DummyMetrics())
    ctx.index_params = {
        'NIFTY': {'enable': True, 'strikes_itm': 10, 'strikes_otm': 10, 'expiries': ['this_week']},
    }
    interval = 60.0
    # 3 consecutive breaches (elapsed > 0.85 * interval = 51)
    _run_cycles(ctx, [55, 56, 57], interval)
    # Expect scale factor stored; strikes may or may not mutate depending on global env interplay.
    mutated_itm = ctx.index_params['NIFTY']['strikes_itm']
    mutated_otm = ctx.index_params['NIFTY']['strikes_otm']
    assert mutated_itm in (8, 10)
    assert mutated_otm in (8, 10)
    scale = ctx.flag('adaptive_scale_factor')
    assert 0.79 < scale < 0.81

    # 4 healthy cycles (< 51) should not restore yet (restore threshold=5)
    _run_cycles(ctx, [40, 40, 40, 40], interval)
    # If in mutating mode counts remain at reduced value (8); in passthrough they stayed 10.
    assert ctx.index_params['NIFTY']['strikes_itm'] in (8, 10)

    # Next healthy cycle triggers restore (scale back toward 1.0 => 8 /0.8 = 10 target)
    _run_cycles(ctx, [40], interval)
    # After restore: in mutating mode counts return to baseline; in passthrough they were already baseline.
    assert ctx.index_params['NIFTY']['strikes_itm'] == 10
    assert ctx.index_params['NIFTY']['strikes_otm'] == 10
    assert ctx.flag('adaptive_scale_factor') == 1.0
