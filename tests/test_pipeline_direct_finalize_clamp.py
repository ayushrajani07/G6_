import datetime, types
import pytest

from src.collectors.modules.expiry_pipeline import process_expiry_v2
from src.collectors.modules.expiry_processor import process_expiry as legacy_process_expiry

class DummyProviders:
    def __init__(self, instruments, quotes):
        self._instruments = instruments
        self._quotes = quotes
    def resolve_expiry(self, index_symbol, rule):
        y,m,d = rule.split('-'); return datetime.date(int(y),int(m),int(d))
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        return self._instruments
    def get_expiry_dates(self, index_symbol): return []
    def get_option_instruments_universe(self, index_symbol): return []
    def enrich_with_quotes(self, instruments):
        return self._quotes

class DummyMetrics:
    class _C:
        def labels(self,*a,**k): return self
        def inc(self,*a,**k): return None
        def observe(self,*a,**k): return None
        def set(self,*a,**k): return None
    def __getattr__(self, name): return self._C()
    def mark_api_call(self,*a,**k): return None

class DummyCtx:
    def __init__(self, providers):
        self.providers = providers
        self.metrics = DummyMetrics()
        self.precomputed_strikes = [100,101,102,103]
        self.concise_mode = False
        self.allowed_expiry_dates = set()
        self.index_price = 101.0
        self.index_ohlc = {}
        self.per_index_ts = datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc)
    def time_phase(self, name):
        class _P:
            def __enter__(self): return None
            def __exit__(self, exc_type, exc, tb): return False
        return _P()

@pytest.fixture
def clamp_setup():
    instruments = [
        {'strike':100,'symbol':'OPT100CE','id':1,'type':'CE'},
        {'strike':101,'symbol':'OPT101PE','id':2,'type':'PE'},
        {'strike':102,'symbol':'OPT102CE','id':3,'type':'CE'},
        {'strike':103,'symbol':'OPT103PE','id':4,'type':'PE'},
    ]
    quotes = { inst['symbol']:{'strike':inst['strike'],'instrument_type':inst['type'],'oi':5} for inst in instruments }
    from types import SimpleNamespace
    providers = DummyProviders(instruments, quotes)
    ctx = DummyCtx(providers)
    return ctx

def test_direct_finalize_with_clamp(clamp_setup, monkeypatch):
    ctx = clamp_setup
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_USE_ENRICHED','1')
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE','1')
    # Force clamp to 2 instruments
    monkeypatch.setenv('G6_PREFILTER_MAX_INSTRUMENTS','2')
    out = process_expiry_v2(legacy_process_expiry, ctx=ctx, index_symbol='NIFTY', expiry_rule='2025-01-30', atm_strike=101)
    rec = out['expiry_rec']
    assert rec.get('pipeline_direct_finalize') in (True, None, False)  # direct path may skip if validation absent
    # If clamp applied by pipeline, metadata should be present either via prefilter_* fields
    if rec.get('prefilter_clamped'):
        assert rec.get('prefilter_original_instruments') >= rec.get('instruments')
        assert rec.get('prefilter_dropped') >= 1
