import os
from src.orchestrator.parity_harness import run_parity_cycle


class _MiniConfigEnhanced:
    """Minimal config enabling enhanced + parallel flags for parity coverage.

    Mirrors the basic parity test but sets a slightly wider strike window to
    exercise additional code paths while still remaining fast.
    """
    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._index_params = {
            'NIFTY': {
                'enable': True,
                'expiries': ['this_week'],
                'strikes_itm': 3,
                'strikes_otm': 3,
            }
        }
    def index_params(self):
        return self._index_params
    def data_dir(self):
        return self._base_dir
    def get(self, key, default=None):
        if key == 'greeks':
            return {'enabled': False}
        return default


def test_orchestrator_parity_enhanced_parallel(tmp_path):
    # Force mock + market open plus enhanced/parallel paths
    os.environ['G6_USE_MOCK_PROVIDER'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    os.environ['G6_PARALLEL_INDICES'] = '1'  # exercise parallel branch even if no material concurrency
    os.environ['G6_ADAPTIVE_STRIKE_SCALING'] = '0'  # keep deterministic strike window
    cfg = _MiniConfigEnhanced(str(tmp_path))
    data = run_parity_cycle(cfg)
    assert 'legacy' in data and 'new' in data
    # Structural assertions reused from basic parity test
    legacy = data['legacy']; new = data['new']
    assert set(legacy.keys()) == set(new.keys())
    for idx in legacy.keys():
        assert legacy[idx]['expiries'] == new[idx]['expiries']
        # Option counts may differ but must be non-negative and keys aligned
        assert set(legacy[idx]['expiry_option_counts'].keys()) == set(new[idx]['expiry_option_counts'].keys())
        for exp in legacy[idx]['expiry_option_counts']:
            assert legacy[idx]['expiry_option_counts'][exp] >= 0
            assert new[idx]['expiry_option_counts'][exp] >= 0
        assert legacy[idx]['total_options'] >= 0
        assert new[idx]['total_options'] >= 0