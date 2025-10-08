import importlib

shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
gating_mod = importlib.import_module('src.collectors.pipeline.gating')


def test_gating_dryrun_window_progress(monkeypatch):
    # Force dryrun mode
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','dryrun')
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','10')
    # Reset internal store by reloading module (simple approach)
    import importlib as _il
    _il.reload(gating_mod)

    # Fabricate shadow meta snapshots with alternating diff counts
    last_decision = None
    for i in range(6):
        meta = {
            'parity_diff_count': 0 if i % 2 == 0 else 1,
            'parity_diff_fields': () if i % 2 == 0 else ('strike_count',),
        }
        last_decision = gating_mod.decide('NIFTY','this_week', meta)
        assert last_decision['mode'] == 'dryrun'
        assert last_decision['promote'] is False
        if last_decision['window_size']:
            ratio = last_decision['parity_ok_ratio']
            assert 0.0 <= ratio <= 1.0
    assert last_decision is not None
    total = last_decision['window_size']
    ratio = last_decision['parity_ok_ratio']
    if total:  # only assert ratio band when we actually collected samples
        assert total <= 10
        assert 0.3 <= ratio <= 0.7


def test_gating_off_mode_no_window(monkeypatch):
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','off')
    import importlib as _il
    _il.reload(gating_mod)
    meta = {'parity_diff_count':0,'parity_diff_fields':()}
    decision = gating_mod.decide('NIFTY','this_week', meta)
    assert decision['mode'] == 'off'
    assert decision['parity_ok_ratio'] in (None, 0.0)  # None expected (no samples)
    assert decision['window_size'] in (0,)


def test_shadow_pipeline_includes_gating(monkeypatch):
    # Minimal legacy snapshot vs shadow snapshot parity to ensure gating_decision injected
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','dryrun')
    from types import SimpleNamespace
    ctx = SimpleNamespace(time_phase=lambda name: __import__('contextlib').nullcontext())
    # Provide dummy phases by monkeypatching phases module inside shadow
    phases = importlib.import_module('src.collectors.pipeline.phases')
    def _noop(*a, **k):
        return None
    monkeypatch.setattr(phases, 'phase_resolve', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_fetch', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_prefilter', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_enrich', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_preventive_validate', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_salvage', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_coverage', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_iv', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_greeks', _noop, raising=True)
    monkeypatch.setattr(phases, 'phase_persist_sim', _noop, raising=True)

    settings = type('S', (), {})()
    legacy_snapshot = {'expiry_date': '2025-10-01','strike_count':0,'instrument_count':0,'enriched_keys':0}
    state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[], legacy_snapshot=legacy_snapshot)
    assert state is not None
    decision = state.meta.get('gating_decision')
    assert decision and decision.get('mode') == 'dryrun'
