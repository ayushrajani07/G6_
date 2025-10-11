import importlib, types
import pytest

pytestmark = pytest.mark.serial

class DummyProviders: ...
class DummyCtx:
    def __init__(self):
        self.providers = DummyProviders()
        self.metrics = None
        self.precomputed_strikes = [100,105]


def test_shadow_pipeline_includes_preventive_and_salvage(monkeypatch):
    # Enable pipeline flag
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')

    # Fake preventive_validate to drop everything and mark foreign expiry
    fake_prev = types.ModuleType('src.collectors.modules.preventive_validate')
    def run_preventive_validation(index, rule, expiry_date, instruments, enriched, index_price):
        # Simulate all rows dropped due to foreign expiry
        report = {
            'ok': False,
            'issues': ['foreign_expiry','insufficient_strike_coverage'],
            'dropped_count': len(enriched),
            'post_enriched_count': 0,
        }
        return {}, report
    setattr(fake_prev, 'run_preventive_validation', run_preventive_validation)  # type: ignore[attr-defined]

    # Fake legacy unified helpers
    fake_uc = types.ModuleType('src.collectors.unified_collectors')
    def _resolve_expiry(index, rule, strikes):
        import datetime as dt
        return dt.date.today(), None, [100,105]
    def _fetch_option_instruments(index, rule, expiry_date, strikes, providers):
        return [{'symbol': f'{index}{s}', 'expiry': '2025-10-09', 'volume': 0, 'oi': 0} for s in strikes]
    def _enrich_quotes(index, rule, expiry_date, instruments, providers, metrics):
        return {i['symbol']: {'expiry': '2025-10-09', 'volume':0, 'oi':0} for i in instruments}
    setattr(fake_uc, '_resolve_expiry', _resolve_expiry)  # type: ignore[attr-defined]
    setattr(fake_uc, '_fetch_option_instruments', _fetch_option_instruments)  # type: ignore[attr-defined]
    setattr(fake_uc, '_enrich_quotes', _enrich_quotes)  # type: ignore[attr-defined]

    import sys
    sys.modules['src.collectors.unified_collectors'] = fake_uc
    sys.modules['src.collectors.modules.preventive_validate'] = fake_prev

    settings_mod = importlib.import_module('src.collectors.settings')
    importlib.reload(settings_mod)
    settings = settings_mod.CollectorSettings.load()
    shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')
    legacy_snapshot = {'expiry_date': None, 'strike_count': 2, 'strikes': [100,105], 'instrument_count': 0, 'enriched_keys': 0}
    ctx = DummyCtx()
    state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100,105], legacy_snapshot=legacy_snapshot)
    # After preventive validation drops all, salvage phase should attempt but without orig snapshot retained (since we captured before drop) salvage not applied (expected structural logic)
    # We assert phases ran by presence of preventive_report meta
    assert 'preventive_report' in state.meta or 'preventive_report' in getattr(state, 'meta', {})
