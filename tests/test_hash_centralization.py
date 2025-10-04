import copy
from scripts.summary.hashing import compute_all_panel_hashes

def test_hashes_stable_when_status_unchanged():
    status = {
        'indices': ['NIFTY','BANKNIFTY'],
        'alerts': [{'id':1,'t':'x'}],
        'analytics': {'a':1,'b':2},
        'performance': {'latency_ms': 5},
        'storage': {'lag': 0, 'queue_depth': 1},
        'app': {'version': '1.2.3'},
    }
    h1 = compute_all_panel_hashes(status)
    h2 = compute_all_panel_hashes(copy.deepcopy(status))
    assert h1 == h2


def test_only_changed_panel_hash_mutates():
    status = {
        'indices': ['NIFTY','BANKNIFTY'],
        'alerts': [],
        'analytics': {'a':1,'b':2},
        'performance': {'latency_ms': 5},
        'storage': {'lag': 0, 'queue_depth': 1},
        'app': {'version': '1.2.3'},
    }
    base = compute_all_panel_hashes(status)
    # mutate analytics only
    status2 = copy.deepcopy(status)
    status2['analytics']['b'] = 99
    changed = compute_all_panel_hashes(status2)
    diff_keys = [k for k in base if base[k] != changed[k]]
    # header may also change if indices or version changed (they did not), ensure analytics updated
    assert 'analytics' in diff_keys
    # ensure unrelated panel hashes remained same
    for k in base:
        if k != 'analytics':
            assert base[k] == changed[k]
