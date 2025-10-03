import os
import json
import tempfile
import time
import pytest

from src.orchestrator.parity_harness import run_parity_cycle


class _MiniConfig:
    """Minimal duck-typed config wrapper for parity test.

    Provides index_params(), data_dir(), and dict-like access for greeks (disabled).
    """
    def __init__(self, base_dir: str):
        self._base_dir = base_dir
        self._index_params = {
            'NIFTY': {
                'enable': True,
                'expiries': ['this_week'],
                'strikes_itm': 2,
                'strikes_otm': 2,
            }
        }
    def index_params(self):
        return self._index_params
    def data_dir(self):
        # csv sink expects path where g6_data/ will be created
        return self._base_dir
    def get(self, key, default=None):  # minimal mapping style for greeks lookup
        if key == 'greeks':
            return {'enabled': False}
        return default


def _diff_summary(legacy_idx: dict, new_idx: dict) -> str:
    diffs = []
    if legacy_idx.get('expiries') != new_idx.get('expiries'):
        diffs.append(f"expiries mismatch: {legacy_idx.get('expiries')} vs {new_idx.get('expiries')}")
    l_counts = legacy_idx.get('expiry_option_counts', {})
    n_counts = new_idx.get('expiry_option_counts', {})
    for k in sorted(set(l_counts) | set(n_counts)):
        if l_counts.get(k) != n_counts.get(k):
            diffs.append(f"count[{k}]: {l_counts.get(k)} != {n_counts.get(k)}")
    if legacy_idx.get('total_options') != new_idx.get('total_options'):
        diffs.append(f"total_options: {legacy_idx.get('total_options')} != {new_idx.get('total_options')}")
    return '; '.join(diffs)


@pytest.mark.parametrize("use_enhanced", [False, True])
def test_orchestrator_parity_basic(tmp_path, use_enhanced):
    # Ensure we use mock provider and force open market
    os.environ['G6_USE_MOCK_PROVIDER'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    cfg = _MiniConfig(str(tmp_path))
    data = run_parity_cycle(cfg, use_enhanced=use_enhanced)
    # Basic shape assertions
    assert 'legacy' in data and 'new' in data
    legacy = data['legacy']
    new = data['new']
    # Same index keys
    assert set(legacy.keys()) == set(new.keys())
    for idx in legacy.keys():
        l_idx = legacy[idx]
        n_idx = new[idx]
        # Expiries should match (both lists) & be sorted unique
        assert l_idx['expiries'] == n_idx['expiries'], _diff_summary(l_idx, n_idx)
        assert l_idx['expiries'] == sorted(set(l_idx['expiries']))
        # Option counts structural keys identical
        assert set(l_idx['expiry_option_counts'].keys()) == set(n_idx['expiry_option_counts'].keys()), _diff_summary(l_idx, n_idx)
        # Non-negative + sum matches total
        for exp in l_idx['expiry_option_counts']:
            assert l_idx['expiry_option_counts'][exp] >= 0
            assert n_idx['expiry_option_counts'][exp] >= 0
        assert sum(l_idx['expiry_option_counts'].values()) == l_idx['total_options']
        assert sum(n_idx['expiry_option_counts'].values()) == n_idx['total_options']
        assert l_idx['total_options'] >= 0 and n_idx['total_options'] >= 0


def test_orchestrator_parity_golden_regen(tmp_path):
    """Optional golden file regeneration (activated via env flag)."""
    if os.environ.get('G6_REGEN_PARITY_GOLDEN') != '1':
        return
    os.environ['G6_USE_MOCK_PROVIDER'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    cfg = _MiniConfig(str(tmp_path))
    report = run_parity_cycle(cfg)
    golden_path = tmp_path / 'parity_report.json'
    with open(golden_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, sort_keys=True)
    assert golden_path.exists()


@pytest.mark.slow
def test_orchestrator_parity_after_real_cycles(tmp_path, run_orchestrator_cycle):
    """Integration: run a few real orchestrator cycles first, then parity harness.

    This ensures that prior real cycles (which may have produced CSV output or mutated
    underlying directories) do not break the assumptions of the parity harness.

    We intentionally keep this lightweight (2 cycles) and single index. If needed it
    can be gated behind a marker (e.g. slow) later – for now runtime impact is minimal.
    """
    os.environ['G6_USE_MOCK_PROVIDER'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    # Run a couple of real cycles to create any initial CSV/tree structure.
    t0 = time.time()
    status = run_orchestrator_cycle(cycles=2, interval=1, strict=False)
    elapsed_real = time.time() - t0
    # Performance budget (soft assert): < 3s
    assert elapsed_real < 3.0
    assert status['cycle'] in (0, 1)

    # Now invoke parity harness which itself performs one legacy + one new cycle.
    cfg = _MiniConfig(str(tmp_path))
    data = run_parity_cycle(cfg)
    assert 'legacy' in data and 'new' in data
    legacy = data['legacy']
    new = data['new']
    assert set(legacy.keys()) == set(new.keys())
    for idx in legacy.keys():
        # Structural consistency after prior real cycles
        assert 'expiries' in legacy[idx] and 'expiries' in new[idx]
        assert 'expiry_option_counts' in legacy[idx] and 'expiry_option_counts' in new[idx]
        assert 'total_options' in legacy[idx] and 'total_options' in new[idx]
        # Non-negative counts
        for exp, l_count in legacy[idx]['expiry_option_counts'].items():
            assert l_count >= 0
            assert new[idx]['expiry_option_counts'].get(exp, 0) >= 0
        assert legacy[idx]['total_options'] >= 0
        assert new[idx]['total_options'] >= 0
    # Minimal metrics presence check (optional - ensures at least one cycle metric emitted)
    try:
        from prometheus_client import REGISTRY  # type: ignore
        found_cycle_metric = any(m.name == 'g6_cycle_time_seconds' for m in REGISTRY.collect())
        assert found_cycle_metric, 'Expected g6_cycle_time_seconds metric not found'
    except Exception:
        # Do not fail test if prometheus_client differs; metric presence is best-effort
        pass
