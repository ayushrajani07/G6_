from scripts.summary.hashing import compute_all_panel_hashes, _stable, _canonical  # type: ignore
import math, copy


def build_status(**overrides):
    base = {
        'indices': ['X','Y'],
        'alerts': [{'id': 1, 'sev': 'low'}],
        'analytics': {'float_one': 1.0, 'nested': {'b': 2, 'a': 1}},
        'performance': {'latency_ms': 5.0},
        'storage': {'lag': 0, 'queue_depth': 1, 'last_flush_age_sec': -0.0},
        'app': {'version': '0.0.1'},
    }
    base.update(overrides)
    return base


def test_key_order_independence():
    s1 = build_status(analytics={'x': 1, 'y': 2})
    s2 = build_status(analytics={'y': 2, 'x': 1})
    h1 = compute_all_panel_hashes(s1)
    h2 = compute_all_panel_hashes(s2)
    assert h1 == h2


def test_float_normalization_equivalence():
    s1 = build_status(analytics={'v': 1})
    s2 = build_status(analytics={'v': 1.0})
    assert compute_all_panel_hashes(s1)['analytics'] == compute_all_panel_hashes(s2)['analytics']


def test_negative_zero_and_nan_inf():
    s1 = build_status(analytics={'vals': [0.0, -0.0, float('inf'), float('-inf')]})
    s2 = build_status(analytics={'vals': [-0.0, 0.0, math.inf, -math.inf]})
    h1 = compute_all_panel_hashes(s1)['analytics']
    h2 = compute_all_panel_hashes(s2)['analytics']
    assert h1 == h2
    # NaN normalization: two NaNs should hash the same despite JSON not supporting NaN
    s3 = build_status(analytics={'vals': [float('nan'), float('nan')]})
    s4 = build_status(analytics={'vals': [float('nan')]})
    # Even count difference should produce different hash (sequence length matters), but each element canonicalized
    h3 = compute_all_panel_hashes(s3)['analytics']
    h4 = compute_all_panel_hashes(s4)['analytics']
    assert h3 != h4  # length difference


def test_set_ordering_determinism():
    # sets not typical in status but guard determinism if they appear
    a = {'indices': list({'A','B','C'}), 'alerts': [], 'analytics': {'s': set(['k','j','i'])}, 'performance': {}, 'storage': {}, 'app': {'version': 'x'}}
    b = copy.deepcopy(a)
    # mutate internal set ordering by recreating
    b['analytics']['s'] = set(['i','k','j'])
    h1 = compute_all_panel_hashes(a)['analytics']
    h2 = compute_all_panel_hashes(b)['analytics']
    assert h1 == h2
