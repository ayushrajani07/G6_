import importlib, types, sys
import pytest

pytestmark = pytest.mark.serial

class DummyProviders: ...
class DummyCtx:
    def __init__(self):
        self.providers = DummyProviders()
        self.metrics = None
        self.precomputed_strikes = [100,105,110]

def test_shadow_pipeline_phase3_meta(monkeypatch):
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    # Ensure fresh import of shadow & phases after any code modifications
    for _m in ['src.collectors.pipeline.shadow','src.collectors.pipeline.phases']:
        sys.modules.pop(_m, None)
    # Capture originals to restore after test
    orig_modules = {}
    target_mods = [
        'src.collectors.unified_collectors',
        'src.collectors.modules.coverage_eval',
        'src.collectors.modules.iv_estimation',
        'src.collectors.modules.greeks_compute',
        'src.collectors.modules.persist_sim',
    ]
    for m in target_mods:
        if m in sys.modules:
            orig_modules[m] = sys.modules[m]
    try:
        # Provide minimal legacy helpers producing a small enriched set
        fake_uc = types.ModuleType('src.collectors.unified_collectors')
        def _resolve_expiry(index, rule, strikes):
            import datetime as dt
            return dt.date.today(), None, strikes[:3]
        def _fetch_option_instruments(index, rule, expiry_date, strikes, providers):
            return [{'symbol': f'{index}{s}', 'expiry': '2025-10-09', 'volume': 0, 'oi': 0} for s in strikes[:3]]
        def _enrich_quotes(index, rule, expiry_date, instruments, providers, metrics):
            # Provide minimal enriched mapping
            return {i['symbol']: {'expiry': '2025-10-09', 'volume':0, 'oi':0} for i in instruments}
        fake_uc._resolve_expiry = _resolve_expiry  # type: ignore[attr-defined]
        fake_uc._fetch_option_instruments = _fetch_option_instruments  # type: ignore[attr-defined]
        fake_uc._enrich_quotes = _enrich_quotes  # type: ignore[attr-defined]
        sys.modules['src.collectors.unified_collectors'] = fake_uc

        # Stub optional downstream modules so phases succeed deterministically
        fake_cov = types.ModuleType('src.collectors.modules.coverage_eval')
        def compute_coverage(enriched):
            # Return coverage dict with strike and field coverage percentages
            return {'strike': 1.0, 'field': 1.0}
        def coverage_metrics(ctx, instruments, strikes, index, rule, expiry_date):
            return 1.0
        def field_coverage_metrics(ctx, enriched, index, rule, expiry_date):
            return 1.0
        fake_cov.compute_coverage = compute_coverage  # type: ignore[attr-defined]
        fake_cov.coverage_metrics = coverage_metrics  # type: ignore[attr-defined]
        fake_cov.field_coverage_metrics = field_coverage_metrics  # type: ignore[attr-defined]
        sys.modules['src.collectors.modules.coverage_eval'] = fake_cov

        fake_iv = types.ModuleType('src.collectors.modules.iv_estimation')
        def estimate_iv(enriched, index_price=None):
            return {'iv_count': len(enriched)}
        fake_iv.estimate_iv = estimate_iv  # type: ignore[attr-defined]
        sys.modules['src.collectors.modules.iv_estimation'] = fake_iv

        fake_g = types.ModuleType('src.collectors.modules.greeks_compute')
        def compute_greeks(enriched, index_price=None):
            return {'greeks_count': len(enriched)}
        fake_g.compute_greeks = compute_greeks  # type: ignore[attr-defined]
        sys.modules['src.collectors.modules.greeks_compute'] = fake_g

        fake_persist = types.ModuleType('src.collectors.modules.persist_sim')
        def simulate_persist(enriched):
            return {'option_count': len(enriched), 'pcr': 0.0}
        fake_persist.simulate_persist = simulate_persist  # type: ignore[attr-defined]
        sys.modules['src.collectors.modules.persist_sim'] = fake_persist

        settings_mod = importlib.import_module('src.collectors.settings')
        importlib.reload(settings_mod)
        settings = settings_mod.CollectorSettings.load()
        shadow_mod = importlib.import_module('src.collectors.pipeline.shadow')

        legacy_snapshot = {'expiry_date': None, 'strike_count': 3, 'strikes': [100,105,110], 'instrument_count': 0, 'enriched_keys': 0}
        ctx = DummyCtx()
        state = shadow_mod.run_shadow_pipeline(ctx, settings, index='NIFTY', rule='this_week', precomputed_strikes=[100,105,110], legacy_snapshot=legacy_snapshot)

        # Assert meta keys for new phases
        assert 'coverage' in state.meta
        assert 'iv_phase' in state.meta
        assert 'greeks_phase' in state.meta
        assert 'persist_sim' in state.meta
        assert 'parity_hash_v2' in state.meta
        # Basic sanity on hash string length (16 hex chars or 'na')
        ph = state.meta['parity_hash_v2']
        assert ph == 'na' or (isinstance(ph, str) and len(ph) == 16)
    finally:
        # Restore / cleanup modules to avoid leakage into other tests
        for m in target_mods:
            if m in orig_modules:
                sys.modules[m] = orig_modules[m]
            else:
                sys.modules.pop(m, None)
