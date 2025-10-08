import os
import datetime
import types

import pytest

from src.collectors.modules.expiry_pipeline import process_expiry_v2
from src.collectors.modules.expiry_processor import process_expiry as legacy_process_expiry

# Reuse Dummy structures similar to test_expiry_processor_unit but minimal
class DummyProviders:
    def __init__(self, instruments=None):
        self._instruments = instruments or []
    def resolve_expiry(self, index_symbol, rule):
        y,m,d = rule.split('-')
        return datetime.date(int(y), int(m), int(d))
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        return self._instruments
    def get_expiry_dates(self, index_symbol):
        return []
    def get_option_instruments_universe(self, index_symbol):
        return []
    def enrich_with_quotes(self, instruments):
        return {}  # force empty enriched so pipeline triggers synthetic fallback

class DummyMetrics:
    class _C:
        def labels(self, *a, **k): return self
        def inc(self, *a, **k): return None
        def observe(self, *a, **k): return None
        def set(self, *a, **k): return None
    def __getattr__(self, name):
        return self._C()
    def mark_api_call(self, *a, **k):
        return None

class DummyCtx:
    def __init__(self, providers):
        self.providers = providers
        self.metrics = DummyMetrics()
        self.precomputed_strikes = [100]
        self.concise_mode = False
        self.allowed_expiry_dates = set()
        self.index_price = 100.0
        self.index_ohlc = {}
        self.per_index_ts = datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc)

@pytest.mark.parametrize("direct_finalize", [False, True])
def test_pipeline_no_synthetic_flag_after_removal(direct_finalize, monkeypatch):
    providers = DummyProviders(instruments=[{'strike':100,'symbol':'OPT100CE','id':1,'type':'CE'}])
    ctx = DummyCtx(providers)
    # Enable pipeline
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    # Legacy synthetic flag env ignored
    monkeypatch.delenv('G6_DISABLE_SYNTHETIC_FALLBACK', raising=False)
    # Optionally enable direct finalize path (will still have empty validated so should skip)
    if direct_finalize:
        monkeypatch.setenv('G6_COLLECTOR_PIPELINE_USE_ENRICHED','1')
        monkeypatch.setenv('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE','1')
    else:
        monkeypatch.delenv('G6_COLLECTOR_PIPELINE_USE_ENRICHED', raising=False)
        monkeypatch.delenv('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE', raising=False)

    out = process_expiry_v2(legacy_process_expiry, ctx=ctx, index_symbol='NIFTY', expiry_rule='2025-01-30', atm_strike=100)
    assert 'expiry_rec' in out, out
    rec = out['expiry_rec']
    # After removal synthetic_fallback key should not be produced.
    assert 'synthetic_fallback' not in rec
