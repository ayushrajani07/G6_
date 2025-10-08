import importlib, os

gating_mod = importlib.import_module('src.collectors.pipeline.gating')


def test_canary_allowlist_blocks(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','canary')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','1')
    monkeypatch.setenv('G6_SHADOW_CANARY_INDICES','BANKNIFTY')  # allowlist excludes NIFTY
    import importlib as _il
    _il.reload(gating_mod)
    meta = {'parity_diff_count':0,'parity_diff_fields':(),'parity_hash_v2':'abcd1234'}
    d = gating_mod.decide('NIFTY','this_week', meta)
    assert d['reason'] == 'canary_excluded'
    assert d['canary'] is False
    assert d['promote'] is False


def test_canary_percentage_sampling(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','canary')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','1')
    monkeypatch.setenv('G6_SHADOW_CANARY_PCT','0.0001')  # extremely low so most buckets excluded
    import importlib as _il
    _il.reload(gating_mod)
    # Use a hash that will likely fall outside bucket (probability high). If included, still valid.
    meta = {'parity_diff_count':0,'parity_diff_fields':(),'parity_hash_v2':'ffff'}
    d = gating_mod.decide('NIFTY','this_week', meta)
    # Accept either exclusion or activation depending on bucket, but never promotion in canary mode yet
    assert d['promote'] is False
    assert d['mode'] == 'canary'
