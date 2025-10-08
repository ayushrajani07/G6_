import importlib, types

class DummyProviders: ...
class DummyCtx:
    def __init__(self):
        self.providers = DummyProviders()
        self.metrics = None
        self.precomputed_strikes = [100,105,110]


def test_shadow_pipeline_smoke(monkeypatch):
    # Force flag via settings monkeypatch by setting env before import
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    # Provide dummy legacy helper functions used by pipeline phases
    uc_mod = types.SimpleNamespace()
    def _resolve_expiry(index, rule, strikes):
        # Return tuple shaped like (expiry_date, atm, strikes)
        import datetime as dt
        return dt.date.today(), None, strikes
    def _fetch_option_instruments(index, rule, expiry_date, strikes, providers):
        return [{'symbol': f'{index}{s}', 'price': 10, 'volume': 0, 'oi': 0} for s in strikes]
    def _enrich_quotes(index, rule, expiry_date, instruments, providers, metrics):
        return {i['symbol']: {'volume': 0, 'oi':0} for i in instruments}
    monkeypatch.setitem(globals(), '_dummy_uc', uc_mod)
    monkeypatch.setenv('PYTHONHASHSEED','0')  # determinism

    # Inject into import path by creating a fake module
    import sys
    fake_uc = types.ModuleType('src.collectors.unified_collectors')
    fake_uc._resolve_expiry = _resolve_expiry
    fake_uc._fetch_option_instruments = _fetch_option_instruments
    fake_uc._enrich_quotes = _enrich_quotes
    sys.modules['src.collectors.unified_collectors'] = fake_uc

    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    settings = settings_mod.CollectorSettings.load()

    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    legacy_snapshot = {'expiry_date': None, 'strike_count': 3, 'strikes': [100,105,110], 'instrument_count': 0, 'enriched_keys': 0}
    ctx = DummyCtx()
    shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100,105,110], legacy_snapshot=legacy_snapshot)
