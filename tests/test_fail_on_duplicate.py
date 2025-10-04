import os, importlib
from src.metrics import generated as gen

def test_fail_on_duplicate(monkeypatch):
    # Ensure base metric exists
    m = gen.m_metrics_spec_hash_info()
    assert m is not None
    monkeypatch.setenv('G6_METRICS_FAIL_ON_DUP', '1')
    # Trigger duplicate by re-calling registry guard low-level _register
    from src.metrics.cardinality_guard import registry_guard
    try:
        registry_guard._register('gauge', 'g6_metrics_spec_hash_info', 'dup test', [], 1)
    except RuntimeError as e:
        assert 'duplicate metric registration' in str(e)
    else:
        raise AssertionError('Expected RuntimeError on duplicate registration with G6_METRICS_FAIL_ON_DUP=1')
