import importlib

def test_shadow_gating_extra_protected_field_blocks(monkeypatch):
    # Treat strike_count as protected to force block
    monkeypatch.setenv('G6_SHADOW_PROTECTED_FIELDS','strike_count')
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','promote')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','5')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','3')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=None)
    legacy = {'expiry_date': None, 'strike_count': 1, 'strikes': [100], 'instrument_count': 1, 'enriched_keys': 0}
    # Create a few parity-ok samples first (no diff) to reach min_samples
    for _ in range(3):
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100], legacy_snapshot=legacy)
    # Now introduce a diff on strike_count -> protected by env
    legacy2 = dict(legacy)
    legacy2['strike_count'] = 2
    state2 = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100], legacy_snapshot=legacy2)
    decision = state2.meta['gating_decision']
    # Promotion should be blocked due to protected_diff
    assert decision['protected_diff'] is True
    assert decision['reason'] in ('protected_block','observing','waiting_hysteresis','rollback_protected')
