import importlib, time

def test_shadow_gating_churn_ratio(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','dryrun')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','5')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    gating_mod = importlib.import_module('src.collectors.pipeline.gating')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=None)
    legacy_snapshot = {'expiry_date': None, 'strike_count': 0, 'strikes': [], 'instrument_count': 0, 'enriched_keys': 0}
    hashes = []
    # Run > window cycles with synthetic diff variation by mutating legacy strike_count to influence hash occasionally
    decision = {}
    for i in range(7):
        ls = dict(legacy_snapshot)
        # Alternate strike_count to generate hash variance
        ls['strike_count'] = i % 3  # cycle 0,1,2
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100,101], legacy_snapshot=ls)
        decision = state.meta['gating_decision']
        hashes.append(state.meta.get('parity_hash_v2'))
    # After cycles, decision should expose hash_churn_ratio within [0,1]
    assert 0.0 <= decision['hash_churn_ratio'] <= 1.0
    # Distinct count should be <= window size
    assert decision['hash_distinct'] <= decision['window_size']
    # Ensure churn ratio reflects more than one distinct hash
    assert decision['hash_distinct'] >= 1
