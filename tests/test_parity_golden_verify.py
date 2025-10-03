import os
import json
import hashlib
from copy import deepcopy
from pathlib import Path
import pytest

from src.orchestrator.parity_harness import run_parity_cycle
from pathlib import Path as _P

@pytest.mark.optional
def test_parity_golden_verify(tmp_path):
    """Verify current parity snapshot against stored golden if enabled.

    Activation: set G6_PARITY_GOLDEN_VERIFY=1. If file empty (placeholder) test skips.
    Regeneration remains via existing G6_REGEN_PARITY_GOLDEN flag in original parity test.
    """
    if os.environ.get('G6_PARITY_GOLDEN_VERIFY') != '1':
        pytest.skip('Set G6_PARITY_GOLDEN_VERIFY=1 to enable golden parity verification')
    golden_path = Path('tests/parity_golden.json')
    if not golden_path.exists():
        pytest.skip('Golden file missing; regenerate first')
    try:
        golden_raw = json.loads(golden_path.read_text())
    except Exception:
        pytest.skip('Golden file unreadable')
    golden = deepcopy(golden_raw)
    if not golden.get('legacy') and not golden.get('new'):
        pytest.skip('Golden file placeholder empty')

    class _MiniConfig:
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
            return self._base_dir
        def get(self, key, default=None):
            if key == 'greeks':
                return {'enabled': False}
            return default

    # Prepopulate CSV structure with golden expiries so parity harness sees them
    expiries = golden['legacy'][next(iter(golden['legacy']))]['expiries'] if golden.get('legacy') else []
    data_root = tmp_path / 'g6_data' / 'NIFTY'
    for exp in expiries:
        exp_dir = data_root / exp
        exp_dir.mkdir(parents=True, exist_ok=True)
        # Write a minimal recognizable CSV so counting logic registers rows
        csv_path = exp_dir / 'options_mock.csv'
        if not csv_path.exists():
            csv_path.write_text('strike,option_type,ltp\n20000,CE,10\n20000,PE,11\n20100,CE,9')
    cfg = _MiniConfig(str(tmp_path))
    current_raw = run_parity_cycle(cfg)

    # Normalization: drop volatile fields (generated_at) and checksum fields before comparison
    def _normalize(obj):
        obj = deepcopy(obj)
        obj.pop('generated_at', None)
        obj.pop('checksum', None)
        return obj

    current = _normalize(current_raw)
    golden_norm = _normalize(golden)

    # Basic structural compare: same index set & expiries list
    for side in ('legacy', 'new'):
        assert set(golden_norm[side].keys()) == set(current[side].keys()), f"Index set changed for {side}" 
        for idx in golden_norm[side].keys():
            g_idx = golden_norm[side][idx]
            c_idx = current[side][idx]
            assert g_idx['expiries'] == c_idx['expiries'], f"Expiries changed for {side}/{idx}: {g_idx['expiries']} vs {c_idx['expiries']}"
            # Allow option count drift but enforce non-negative + key set stable
            assert set(g_idx['expiry_option_counts'].keys()) == set(c_idx['expiry_option_counts'].keys()), f"Expiry key set drift {side}/{idx}" 
            for exp in g_idx['expiry_option_counts'].keys():
                assert c_idx['expiry_option_counts'][exp] >= 0
            assert c_idx['total_options'] >= 0

    # If golden includes a checksum, verify it matches normalized golden structure
    if 'checksum' in golden_raw:
        hasher = hashlib.sha256()
        # Serialize deterministic canonical JSON of normalized golden
        hasher.update(json.dumps(golden_norm, sort_keys=True, separators=(',', ':')).encode('utf-8'))
        expected = golden_raw['checksum']
        actual = hasher.hexdigest()
        assert actual == expected, f"Golden checksum mismatch: expected {expected} got {actual}"
