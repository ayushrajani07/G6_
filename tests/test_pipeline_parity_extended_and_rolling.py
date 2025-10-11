import os
import math
from src.collectors.pipeline.parity import compute_parity_score, record_parity_score


def make_indices(strike_cov_vals):
    indices = []
    for i, cov in enumerate(strike_cov_vals):
        indices.append({
            'index': f'IDX{i}',
            'option_count': 10 + i,
            'strike_coverage_avg': cov,
            'expiries': [],
        })
    return indices


def test_parity_version_base_without_extended():
    os.environ.pop('G6_PARITY_EXTENDED', None)
    legacy = {'indices': make_indices([0.5, 0.6])}
    pipe = {'indices': make_indices([0.55, 0.65])}
    res = compute_parity_score(legacy, pipe)
    assert res['version'] == 1
    assert 'strike_coverage' not in res['components']


def test_parity_version_extended_includes_component():
    os.environ['G6_PARITY_EXTENDED'] = '1'
    legacy = {'indices': make_indices([0.50, 0.60, 0.55])}
    pipe = {'indices': make_indices([0.52, 0.62, 0.53])}
    res = compute_parity_score(legacy, pipe)
    assert res['version'] == 2
    assert 'strike_coverage' in res['components']
    # Coverage similarity should be high ( > 0.9 ) due to close averages
    assert res['components']['strike_coverage'] > 0.9


def test_parity_extended_missing_component_when_no_values():
    os.environ['G6_PARITY_EXTENDED'] = '1'
    legacy = {'indices': [{'index': 'A', 'option_count': 1}]}
    pipe = {'indices': [{'index': 'A', 'option_count': 1}]}
    res = compute_parity_score(legacy, pipe)
    assert 'strike_coverage' in res['missing']


def test_parity_rolling_window_accumulates():
    os.environ['G6_PARITY_EXTENDED'] = '0'
    os.environ['G6_PARITY_ROLLING_WINDOW'] = '5'
    # Reset internal deque by toggling window first
    from importlib import reload
    import src.collectors.pipeline.parity as parity_mod
    reload(parity_mod)
    scores = [0.5, 0.6, 0.7, 0.8, 0.9]
    info = None
    for s in scores:
        info = parity_mod.record_parity_score(s)
    assert info is not None
    assert info['count'] == 5
    assert info['window'] == 5
    assert math.isclose(info['avg'], sum(scores)/5, rel_tol=1e-9)


def test_parity_rolling_window_reconfigures():
    os.environ['G6_PARITY_ROLLING_WINDOW'] = '3'
    from importlib import reload
    import src.collectors.pipeline.parity as parity_mod
    reload(parity_mod)
    for s in [0.1, 0.2, 0.3]:
        parity_mod.record_parity_score(s)
    # Change window to 2 and record again
    os.environ['G6_PARITY_ROLLING_WINDOW'] = '2'
    info = parity_mod.record_parity_score(0.4)
    assert info['window'] == 2
    assert info['count'] == 2  # should have truncated to last 2 values (0.3,0.4)
    assert 0.34 < info['avg'] < 0.36  # average of 0.3,0.4 = 0.35
