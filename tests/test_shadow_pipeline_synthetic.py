import importlib, types, sys

class DummyProviders: ...
class DummyCtx:
    def __init__(self):
        self.providers = DummyProviders()
        self.metrics = None
        self.precomputed_strikes = [100]


def test_shadow_pipeline_no_synthetic_after_removal(monkeypatch):
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    # Force synthetic not disabled
    monkeypatch.delenv('G6_DISABLE_SYNTHETIC_FALLBACK', raising=False)

    # Minimal helpers returning no enriched to trigger synthetic phase
    fake_uc = types.ModuleType('src.collectors.unified_collectors')
    def _resolve_expiry(index, rule, strikes):
        import datetime as dt
        return dt.date.today(), None, [100]
    def _fetch_option_instruments(index, rule, expiry_date, strikes, providers):
        return [{'symbol': f'{index}{strikes[0]}', 'volume':0, 'oi':0}]
    def _enrich_quotes(index, rule, expiry_date, instruments, providers, metrics):
        return {}  # empty enriched triggers synthetic
    fake_uc._resolve_expiry = _resolve_expiry
    fake_uc._fetch_option_instruments = _fetch_option_instruments
    fake_uc._enrich_quotes = _enrich_quotes
    sys.modules['src.collectors.unified_collectors'] = fake_uc

    # No synthetic fallback module injection (removed); ensure absence does not break shadow pipeline.

    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    settings = settings_mod.CollectorSettings.load()
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    legacy_snapshot = {'expiry_date': None, 'strike_count': 1, 'strikes': [100], 'instrument_count': 0, 'enriched_keys': 0}
    ctx = DummyCtx()
    state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100], legacy_snapshot=legacy_snapshot)
    # After removal synthetic metadata should be absent / False and enriched empty.
    assert not state.meta.get('synthetic_applied')
    assert not state.enriched
