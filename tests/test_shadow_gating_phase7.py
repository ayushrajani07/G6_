import importlib

def test_gating_churn_window_and_authoritative(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','promote')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','8')
    monkeypatch.setenv('G6_SHADOW_CHURN_WINDOW','4')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','4')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_TARGET','0.0')  # force easy promote criteria except streak
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_STREAK','2')
    monkeypatch.setenv('G6_SHADOW_AUTHORITATIVE','1')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=None)
    legacy = {'expiry_date': None, 'strike_count': 0, 'strikes': [], 'instrument_count': 1, 'enriched_keys': 0}
    decisions = []
    for i in range(6):
        ls = dict(legacy)
        ls['strike_count'] = i % 3  # induce churn
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='SENSEX', rule='this_week', precomputed_strikes=[100,101], legacy_snapshot=ls)
        decisions.append(state.meta['gating_decision'])
    last = decisions[-1]
    # churn_window_size should be <= 4 when window active
    assert last.get('churn_window_size') is not None
    assert last['churn_window_size'] <= 4
    # authoritative flag appears only on promotion
    if last.get('promote'):
        assert last.get('authoritative') is True


def test_gating_force_demote(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','promote')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','5')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','3')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_TARGET','0.0')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_STREAK','1')
    monkeypatch.setenv('G6_SHADOW_FORCE_DEMOTE','1')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=None)
    legacy = {'expiry_date': None, 'strike_count': 0, 'strikes': [], 'instrument_count': 1, 'enriched_keys': 0}
    state = None
    for i in range(4):
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100], legacy_snapshot=legacy)
    assert state is not None
    decision = state.meta['gating_decision']
    # Even though targets trivially met, demote forced
    assert decision['promote'] is False
    assert decision['reason'] == 'forced_demote'
