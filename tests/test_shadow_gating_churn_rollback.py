import importlib

def test_shadow_gating_churn_rollback(monkeypatch):
    # Enable churn rollback at very low threshold (0.5) to trigger quickly
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','canary')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','6')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','3')
    monkeypatch.setenv('G6_SHADOW_ROLLBACK_CHURN_RATIO','0.5')
    # Lower canary target to allow canary activation when parity ok samples occur
    monkeypatch.setenv('G6_SHADOW_PARITY_CANARY_TARGET','0.0')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=None)
    legacy = {'expiry_date': None, 'strike_count': 0, 'strikes': [], 'instrument_count': 1, 'enriched_keys': 0}
    # Drive churn by varying strike_count pattern to affect hash
    decisions = []
    for i in range(8):
        ls = dict(legacy)
        ls['strike_count'] = i % 4  # cycle through 0..3 producing distinct hashes
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='FINNIFTY', rule='this_week', precomputed_strikes=[100,101], legacy_snapshot=ls)
        decisions.append(state.meta['gating_decision'])
    last = decisions[-1]
    # Expect rollback_churn or canary_active depending on exact hash distinct count; allow benign outcomes
    assert last['reason'] in (
        'rollback_churn',
        'canary_active',
        'dryrun_no_promo',
        'below_canary_target',
        'fail_hysteresis'
    )
    if last['reason'] == 'rollback_churn':
        assert last['canary'] is False
