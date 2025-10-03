import os

from src.orchestrator.context import RuntimeContext
from src.orchestrator.adaptive import update_strike_scaling
from src.utils.strikes import build_strikes

class DummyMetrics:
    def __init__(self):
        class G:
            def labels(self, **_):
                return self
            def set(self, *_a, **_k):
                pass
        self.strike_depth_scale_factor = G()

class DummyProviders:
    def get_index_data(self, index):
        return 100, {}
    def get_atm_strike(self, index):
        return 100


def test_adaptive_passthrough_does_not_mutate_index_params():
    os.environ['G6_ADAPTIVE_STRIKE_SCALING'] = '1'
    os.environ['G6_ADAPTIVE_SCALE_PASSTHROUGH'] = '1'
    os.environ['G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD'] = '2'
    os.environ['G6_ADAPTIVE_STRIKE_REDUCTION'] = '0.5'

    ctx = RuntimeContext(config={}, providers=DummyProviders(), metrics=DummyMetrics())
    ctx.index_params = {
        'NIFTY': {'enable': True, 'strikes_itm': 8, 'strikes_otm': 8, 'expiries': ['this_week']},
    }
    interval = 60.0

    # Force two breaches to trigger scale change
    update_strike_scaling(ctx, elapsed=55, interval=interval)  # breach 1 (> 51)
    update_strike_scaling(ctx, elapsed=55, interval=interval)  # breach 2 triggers scale

    # Baseline params should remain unchanged in passthrough mode
    assert ctx.index_params['NIFTY']['strikes_itm'] == 8
    assert ctx.index_params['NIFTY']['strikes_otm'] == 8
    scale = ctx.flag('adaptive_scale_factor')
    assert scale < 1.0

    # Strike list built with scale should be shorter than baseline*2+1 (which would be 17)
    strikes_scaled = build_strikes(100, 8, 8, 'NIFTY', scale=scale)
    strikes_baseline = build_strikes(100, 8, 8, 'NIFTY', scale=1.0)
    assert len(strikes_scaled) < len(strikes_baseline)


def test_build_strikes_scale_application_counts():
    # Independent of adaptive logic; verify scale argument reduces counts deterministically
    atm = 100
    base_itm = 10
    base_otm = 10
    scaled = build_strikes(atm, base_itm, base_otm, 'NIFTY', scale=0.5)
    baseline = build_strikes(atm, base_itm, base_otm, 'NIFTY', scale=1.0)
    assert len(scaled) < len(baseline)
    # Ensure ATM retained
    assert atm in scaled
