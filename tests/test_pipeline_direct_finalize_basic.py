import datetime, types, os

import pytest

from src.collectors.modules.expiry_pipeline import process_expiry_v2
from src.collectors.modules.expiry_processor import process_expiry as legacy_process_expiry

class DummyProviders:
    def __init__(self, instruments=None, quotes=None):
        self._instruments = instruments or []
        self._quotes = quotes or {}
        self._expiry_dates = [datetime.date(2025,1,30)]
    def resolve_expiry(self, index_symbol, rule):
        y,m,d = rule.split('-'); return datetime.date(int(y),int(m),int(d))
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        return self._instruments
    def get_expiry_dates(self, index_symbol): return self._expiry_dates
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
        self.precomputed_strikes = [100,101]
        self.concise_mode = False
        self.allowed_expiry_dates = set()
        self.index_price = 101.0
        self.index_ohlc = {}
        self.per_index_ts = datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc)
        self.snapshots_accum = []
        self.build_snapshots = False
        self.mem_flags = {}
        class _CsvSink:
            def write_options_data(self, *a, **k):
                return None
        self.csv_sink = _CsvSink()
        self.influx_sink = None
    def time_phase(self, name):
        class _P:
            def __enter__(self): return None
            def __exit__(self, exc_type, exc, tb): return False
        return _P()

@pytest.fixture
def simple_setup():
    instruments = [
        {'strike':100,'symbol':'OPT100CE','id':1,'type':'CE'},
        {'strike':101,'symbol':'OPT101PE','id':2,'type':'PE'},
    ]
    quotes = {
        'OPT100CE': {'strike':100,'instrument_type':'CE','oi':10},
        'OPT101PE': {'strike':101,'instrument_type':'PE','oi':12},
    }
    providers = DummyProviders(instruments, quotes)
    ctx = DummyCtx(providers)
    return ctx

@pytest.mark.parametrize("direct", [False, True])
def test_direct_finalize_parity(simple_setup, monkeypatch, direct):
    ctx = simple_setup
    # Run legacy for baseline
    legacy_out = legacy_process_expiry(
        ctx=ctx,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        atm_strike=101,
        concise_mode=False,
        precomputed_strikes=ctx.precomputed_strikes,
        expiry_universe_map=None,
        allow_per_option_metrics=True,
        local_compute_greeks=False,
        local_estimate_iv=False,
        greeks_calculator=None,
        risk_free_rate=0.05,
        per_index_ts=ctx.per_index_ts,
        index_price=ctx.index_price,
        index_ohlc=ctx.index_ohlc,
        metrics=ctx.metrics,
        mem_flags={},
        dq_checker=None,
        dq_enabled=False,
        snapshots_accum=ctx.snapshots_accum,
        build_snapshots=False,
        allowed_expiry_dates=set(),
        pcr_snapshot={},
        aggregation_state=types.SimpleNamespace(representative_day_width=0, snapshot_base_time=None, capture=lambda *a,**k: None),
        collector_settings=None,
    )
    # assert legacy_out['success'] is True
    # Enable pipeline with direct finalize flags optionally
    monkeypatch.setenv('G6_COLLECTOR_PIPELINE_V2','1')
    if direct:
        monkeypatch.setenv('G6_COLLECTOR_PIPELINE_USE_ENRICHED','1')
        monkeypatch.setenv('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE','1')
    else:
        monkeypatch.delenv('G6_COLLECTOR_PIPELINE_USE_ENRICHED', raising=False)
        monkeypatch.delenv('G6_COLLECTOR_PIPELINE_DIRECT_FINALIZE', raising=False)
    out = process_expiry_v2(legacy_process_expiry, ctx=ctx, index_symbol='NIFTY', expiry_rule='2025-01-30', atm_strike=101)
    assert out['success'] is True
    rec = out['expiry_rec']
    base_rec = legacy_out['expiry_rec']
    # Parity: instruments & options should match
    assert rec.get('instruments') == base_rec.get('instruments')
    assert rec.get('options') == base_rec.get('options')
    if direct:
        assert rec.get('pipeline_direct_finalize') is True
    else:
        assert rec.get('pipeline_direct_finalize') in (None, False)
