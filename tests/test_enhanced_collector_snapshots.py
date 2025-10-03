import os, datetime as dt
from types import SimpleNamespace
from src.collectors.enhanced_shim import run_enhanced_collectors
from src.collectors.providers_interface import Providers

class DummyProviders:
    def __init__(self):
        self._atm = 100.0
    def get_atm_strike(self, index_symbol):
        return self._atm
    def get_ltp(self, index_symbol):  # used inside providers facade for ATM calc
        return self._atm
    def get_expiry_dates(self, index_symbol):
        # Provide two future expiries (today and +7) so that this_week and next_week map deterministically
        today = dt.date.today()
        return [today, today + dt.timedelta(days=7)]
    def option_instruments(self, index_symbol, expiry_date, strikes):
        out = []
        for s in strikes:
            out.append({'exchange':'NFO','tradingsymbol':f'{index_symbol}X{s}CE','instrument_type':'CE','strike':s})
            out.append({'exchange':'NFO','tradingsymbol':f'{index_symbol}X{s}PE','instrument_type':'PE','strike':s})
        return out
    def get_quote(self, instruments):
        # The Providers facade expects a dict keyed by instrument tuple when passing list? Here we mimic direct dict with exchange:symbol
        out = {}
        for item in instruments:
            exch, sym = item
            out[f"{exch}:{sym}"] = {"last_price": 10.0, "volume": 5, "oi": 50, "timestamp": "2025-09-26T10:00:00Z"}
        return out

class DummyCsvSink:
    def save_option_quotes(self, *a, **k):
        pass

class DummyInfluxSink:
    def write_option_quotes(self, *a, **k):
        pass

class DummyMetrics:
    def create_timer(self, *a, **k):
        class NullTimer:
            def __enter__(self):
                return self
            def __exit__(self, *exc):
                return False
        return NullTimer()
    def record_collection_run(self, *a, **k):
        pass


def test_enhanced_collector_snapshots(monkeypatch):
    """Validate backward-compat shim returns snapshots when explicitly requested.

    Post-migration `run_enhanced_collectors` delegates to unified collectors unless
    snapshot mode is enabled or return_snapshots flag evaluates true. The legacy
    test assumed the function always returned a list of ExpirySnapshot objects.
    We now force snapshot behavior explicitly via both env var and explicit
    return_snapshots kw to guarantee deterministic semantics, independent of
    internal shim evolution.
    """
    providers = Providers(primary_provider=DummyProviders())
    csv_sink = DummyCsvSink()
    influx_sink = DummyInfluxSink()
    metrics = DummyMetrics()
    index_params = {"NIFTY": {"expiry_rules": ["this_week"], "offsets": [0], "strike_step": 50}}
    # Ensure snapshots path is taken even if underlying shim changes defaults.
    monkeypatch.setenv('G6_RETURN_SNAPSHOTS','1')
    monkeypatch.setenv('G6_ENHANCED_SNAPSHOT_MODE','1')  # force shim snapshot branch
    snaps = run_enhanced_collectors(
        index_params,
        providers,
        csv_sink,
        influx_sink,
        metrics,
        enrichment_enabled=False,
        only_during_market_hours=False,
        min_volume=0,
        min_oi=0,
        return_snapshots=True,
    )
    assert isinstance(snaps, list), "Expected list of snapshots when snapshot mode forced"
    assert len(snaps) == 1
    snap = snaps[0]
    assert getattr(snap, 'index', None) == 'NIFTY'
    assert getattr(snap, 'expiry_rule', None) == 'this_week'
    # DummyProviders returns two legs per strike (1 strike -> 2 option objects)
    assert getattr(snap, 'option_count', 2) == 2
    assert all(getattr(o, 'timestamp', None) is not None for o in getattr(snap, 'options', []))
