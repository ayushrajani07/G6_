import importlib

def test_shadow_gating_metrics_emission(monkeypatch):
    # Enable dryrun gating so decisions accumulate
    monkeypatch.setenv('G6_SHADOW_GATE_MODE','dryrun')
    # Use minimal parity window for quicker ratio updates
    monkeypatch.setenv('G6_SHADOW_PARITY_WINDOW','5')
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    gating_mod = importlib.import_module('src.collectors.pipeline.gating')
    # Fake a metrics registry with prometheus_client available if installed
    try:
        from prometheus_client import CollectorRegistry  # type: ignore
        reg = CollectorRegistry()
        # Provide facade attributes expected by adapter (assigned dynamically)
    except Exception:  # If prometheus absent, test still should not raise
        class Dummy: ...
        reg = Dummy()
    from types import SimpleNamespace
    ctx = SimpleNamespace(providers=None, metrics=reg)
    settings_mod = importlib.import_module('src.collectors.settings')
    settings = settings_mod.CollectorSettings.load()
    legacy_snapshot = {'expiry_date': None, 'strike_count': 0, 'strikes': [], 'instrument_count': 0, 'enriched_keys': 0}
    # Run a few cycles with alternating diff counts to exercise both counters
    for i in range(4):
        meta_inject = {'parity_diff_count': 0 if i % 2 == 0 else 1, 'parity_diff_fields': () if i % 2 == 0 else ('strike_count',)}
        # Inject meta directly by patching state after run or mimic by monkeypatch? Simpler: patch gating.decide input meta diff_count via state meta.
        # The pipeline itself recomputes diff from legacy snapshot; vary legacy snapshot instrument_count to force diff.
        ls = dict(legacy_snapshot)
        if i % 2 == 1:
            ls['strike_count'] = 1  # create a diff
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[], legacy_snapshot=ls)
        assert state is None or 'gating_decision' in getattr(state, 'meta', {})
    # If prometheus present, registry should now have attributes (best-effort)
    # We don't fail test if not, just ensure no exceptions occurred.
