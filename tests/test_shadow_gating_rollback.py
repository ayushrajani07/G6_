import importlib

def test_shadow_gating_protected_rollback(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','promote')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','5')
    # Set low rollback threshold
    monkeypatch.setenv('G6_SHADOW_ROLLBACK_PROTECTED_THRESHOLD','2')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=None)
    base_legacy = {'expiry_date': '2024-01-01', 'strike_count': 1, 'strikes': [100], 'instrument_count': 1, 'enriched_keys': 0}
    # Create two cycles with protected diffs (change instrument_count)
    for i in range(2):
        ls = dict(base_legacy)
        # Force diff by toggling instrument_count
        ls['instrument_count'] = 1 + i
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='BANKNIFTY', rule='this_week', precomputed_strikes=[100,101], legacy_snapshot=ls)
        decision = state.meta['gating_decision']
    assert decision['reason'] in ('rollback_protected','protected_block')
    # When rollback triggered, promote must be false
    assert decision['promote'] is False
