import datetime
import types
import pytest

from src.collectors.modules.expiry_processor import process_expiry

# Minimal dummy helpers / context to drive the function deterministically

class DummyMetrics:
    """Very small metrics stub.

    Any accessed attribute returns an object with .labels()/.inc()/.observe() no-ops.
    This lets underlying persistence / finalize helpers call metrics without blowing up.
    """
    class _Counter:
        def labels(self, *a, **k):
            return self
        def inc(self, *a, **k):
            return None
        def observe(self, *a, **k):
            return None
        def set(self, *a, **k):
            return None
    def __init__(self):
        # Provide specific counters accessed in exception path
        self.collection_errors = self._Counter()
        self.total_errors = self._Counter()
        self.data_errors = self._Counter()
        # Provide commonly referenced gauges/counters used later in pipeline
        self.options_collected = self._Counter()
        self.options_processed_total = self._Counter()
        self.index_options_processed_total = self._Counter()
        self.pcr = self._Counter()
        # Generic fallbacks for other metrics names
    def __getattr__(self, name):  # noqa: D401 - generic stub
        return self._Counter()
    def mark_api_call(self, *a, **k):  # mimic interface used by helpers
        return None

class DummyProviders:
    """Provider stub matching subset of unified_collectors expectations.

    Key behaviors:
      - resolve_expiry: parses ISO date rule
      - get_option_instruments: returns list of instrument dicts (each must have 'strike' & 'symbol')
      - enrich_with_quotes: returns mapping keyed by instrument['symbol']
    """
    def __init__(self, instruments=None, quotes=None, expiry_dates=None):
        self._instruments = instruments or []
        self._quotes = quotes or {}
        self._expiry_dates = expiry_dates or []
    def get_expiry_dates(self, index_symbol):
        return self._expiry_dates
    def get_option_instruments_universe(self, index_symbol):
        return []
    def resolve_expiry(self, index_symbol, rule):
        y,m,d = rule.split('-')
        import datetime as _dt
        return _dt.date(int(y), int(m), int(d))
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        return self._instruments
    def enrich_with_quotes(self, instruments):
        # If explicit quotes provided, return them; else build simple deterministic structure
        if self._quotes:
            return self._quotes
        out = {}
        for inst in instruments:
            sym = inst.get('symbol') or f"{inst.get('strike')}-GEN"
            out[sym] = {'strike': inst.get('strike'), 'instrument_type': inst.get('type') or inst.get('instrument_type') or 'CE', 'oi':1}
        return out

class DummyCsvSink:
    def write_options_data(self, *a, **k):
        pass

class DummyCtx:
    def __init__(self, providers):
        self.providers = providers
        self.csv_sink = DummyCsvSink()
        self.influx_sink = None
        # Provide metrics attribute expected by deeper helpers
        self.metrics = DummyMetrics()
    def time_phase(self, name):
        # simple context manager stub
        class _P:
            def __enter__(self):  # noqa: D401 - simple stub
                return None
            def __exit__(self, exc_type, exc, tb):  # noqa: D401 - simple stub
                return False
        return _P()

@pytest.fixture
def base_args():
    return dict(
        concise_mode=False,
        precomputed_strikes=[100, 101, 102],
        expiry_universe_map=None,
        allow_per_option_metrics=True,
        local_compute_greeks=False,
        local_estimate_iv=False,
        greeks_calculator=None,
        risk_free_rate=0.05,
        per_index_ts=datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc),
        index_price=100.5,
        index_ohlc={},
        metrics=DummyMetrics(),
        mem_flags={},
        dq_checker=None,
        dq_enabled=False,
        refactor_debug=False,
        parity_accum=[],
        snapshots_accum=[],
        build_snapshots=False,
        allowed_expiry_dates=set(),
        pcr_snapshot={},
        aggregation_state=types.SimpleNamespace(representative_day_width=0, snapshot_base_time=None, capture=lambda *a, **k: None),
    )


def test_success_path(base_args):
    providers = DummyProviders(
        instruments=[
            {'strike':100,'id':1,'type':'CE','symbol':'OPT100CE'},
            {'strike':101,'id':2,'type':'PE','symbol':'OPT101PE'}
        ],
        quotes={
            'OPT100CE': {'strike':100,'instrument_type':'CE','oi':10},
            'OPT101PE': {'strike':101,'instrument_type':'PE','oi':15},
        },
    )
    ctx = DummyCtx(providers)
    out = process_expiry(
        ctx=ctx,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        atm_strike=101,
        **base_args
    )
    assert 'expiry_rec' in out, out
    assert out['success'] is True, out
    assert out['option_count'] == 2
    assert out['expiry_rec']['options'] == 2


def test_no_instruments_path(base_args):
    providers = DummyProviders(instruments=[], quotes={})
    ctx = DummyCtx(providers)
    out = process_expiry(
        ctx=ctx,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        atm_strike=101,
        **base_args
    )
    assert 'expiry_rec' in out
    assert out['expiry_rec']['instruments'] == 0
    assert out['success'] is False


def test_no_synthetic_flag_present_after_removal(base_args):
    class _ProvFallback(DummyProviders):
        def enrich_with_quotes(self, instruments):
            return {}
    providers = _ProvFallback(instruments=[{'strike':100,'id':'X','symbol':'OPT100CE','type':'CE'}], quotes={})
    ctx = DummyCtx(providers)
    out = process_expiry(
        ctx=ctx,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        atm_strike=101,
        **base_args
    )
    assert 'expiry_rec' in out
    assert 'synthetic_fallback' not in out['expiry_rec']
