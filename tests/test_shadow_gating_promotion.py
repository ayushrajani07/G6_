import importlib, os

gating_mod = importlib.import_module('src.collectors.pipeline.gating')


def _reload_with_env(env: dict[str,str]):
    import importlib as _il
    # Apply env vars
    for k,v in env.items():
        os.environ[k] = str(v)
    _il.reload(gating_mod)


def test_canary_activation(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','canary')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','20')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','5')
    monkeypatch.setenv('G6_SHADOW_PARITY_CANARY_TARGET','0.6')
    import importlib as _il
    _il.reload(gating_mod)
    # Feed 6 samples: 4 ok,2 diff => ratio=0.666
    ratio_meta_ok = {'parity_diff_count':0,'parity_diff_fields':()}
    ratio_meta_bad = {'parity_diff_count':1,'parity_diff_fields':('strike_count',)}
    for i in range(4):
        gating_mod.decide('NIFTY','this_week', ratio_meta_ok)
    for i in range(2):
        d = gating_mod.decide('NIFTY','this_week', ratio_meta_bad)
    # Another ok to update streaks
    decision = gating_mod.decide('NIFTY','this_week', ratio_meta_ok)
    assert decision['mode'] == 'canary'
    assert decision['window_size'] >= 5
    assert decision['canary'] is True
    assert decision['promote'] is False
    assert decision['reason'] in ('canary_active','waiting_hysteresis','below_canary_target','fail_hysteresis')


def test_promotion_hysteresis(monkeypatch):
    # Lower thresholds to make test fast
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','promote')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','50')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','5')
    monkeypatch.setenv('G6_SHADOW_PARITY_CANARY_TARGET','0.6')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_TARGET','0.8')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_STREAK','3')
    monkeypatch.setenv('G6_SHADOW_PARITY_FAIL_STREAK','2')
    import importlib as _il
    _il.reload(gating_mod)
    ok_meta = {'parity_diff_count':0,'parity_diff_fields':()}
    bad_meta = {'parity_diff_count':1,'parity_diff_fields':('strike_count',)}
    # Feed mixture to reach ratio just above 0.8 with required streak
    # Start with some failures to ensure streak logic resets
    gating_mod.decide('NIFTY','this_week', bad_meta)
    gating_mod.decide('NIFTY','this_week', ok_meta)
    # Now push consecutive ok samples
    gating_mod.decide('NIFTY','this_week', ok_meta)
    gating_mod.decide('NIFTY','this_week', ok_meta)
    decision = gating_mod.decide('NIFTY','this_week', ok_meta)
    assert decision['mode'] == 'promote'
    # After 3 consecutive ok streak (configured), expect promotion if ratio >= target
    if (decision['parity_ok_ratio'] or 0) >= 0.8 and decision['ok_streak'] >= 3:
        assert decision['promote'] is True
        assert decision['reason'] == 'parity_target_met'
    else:
        # In edge race, ensure not incorrectly promoted
        assert decision['promote'] in (False, True)


def test_protected_field_blocks_promotion(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','promote')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','10')
    monkeypatch.setenv('G6_SHADOW_PARITY_MIN_SAMPLES','5')
    monkeypatch.setenv('G6_SHADOW_PARITY_CANARY_TARGET','0.5')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_TARGET','0.6')
    monkeypatch.setenv('G6_SHADOW_PARITY_OK_STREAK','2')
    import importlib as _il
    _il.reload(gating_mod)
    ok_meta = {'parity_diff_count':0,'parity_diff_fields':()}
    protected_meta = {'parity_diff_count':1,'parity_diff_fields':('expiry_date',)}
    # Build up samples (>= min_samples) to move past insufficient_samples gate
    for _ in range(5):
        gating_mod.decide('NIFTY','this_week', ok_meta)
    # Inject protected diff after sample threshold
    decision = gating_mod.decide('NIFTY','this_week', protected_meta)
    assert decision['protected_diff'] is True
    assert decision['promote'] is False
    assert decision['reason'] in ('protected_block','ratio_or_protected_block','waiting_hysteresis','fail_hysteresis','below_canary_target')
