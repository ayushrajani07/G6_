import time, types
from src.collectors.unified_collectors import run_unified_collectors

import datetime

class ProvidersBootstrap:
    def __init__(self):
        self.primary_provider = self
        today = datetime.date.today()
        self._expiries = [today + datetime.timedelta(days=7)]
    def get_expiry_dates(self, index_symbol):
        return list(self._expiries)
    def resolve_expiry(self, index_symbol, rule):
        return self._expiries[0]
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        # minimal instrument list (ATM only) to drive a small processing path
        return [ {'strike': 21000, 'instrument_type': 'CE'}, {'strike':21000,'instrument_type':'PE'} ]
    def enrich_with_quotes(self, instruments):
        return { f"{inst['strike']}{inst['instrument_type']}": { 'strike': inst['strike'], 'instrument_type': inst['instrument_type'], 'last_price': 1.0, 'oi': 10, 'volume': 1, 'avg_price':1.0 } for inst in instruments }
    def get_atm_strike(self, index_symbol):
        return 21000
    def get_index_data(self, index_symbol):
        return 21000.0, {'open':20900,'high':21100,'low':20800,'close':21050}
    def pop_synthetic_quote_usage(self):
        return 0, False

class DummyCsvSink:  # minimal no-op
    def write_options_data(self, *a, **k): return None
    def write_overview_snapshot(self, *a, **k): return None

class DummyInflux:
    def write_options_data(self, *a, **k): pass
    def write_overview_snapshot(self, *a, **k): pass

class DummyGauge:
    def __init__(self):
        self._val = 0
    def set(self, v): self._val = v
    def inc(self, n=1): self._val += n
    def get(self): return self._val

class DummySummary:
    def __init__(self): self._obs = []
    def observe(self, v): self._obs.append(v)

class MetricsBootstrap:
    def __init__(self):
        self.phase_duration_seconds = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(observe=lambda v: self._record_phase(phase, v)))
        self.phase_failures_total = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(inc=lambda : None))
        self._phases = {}
        # Attributes required by memory_pressure & metrics_updater finalize
        self.memory_pressure_level = DummyGauge()
        self.collection_duration = DummySummary()
        self.collection_cycles = DummyGauge()
        self.collection_success_rate = DummyGauge()
        self.api_success_rate = DummyGauge()
        self.api_response_time = DummyGauge()
        self.avg_cycle_time = DummyGauge()
        self.cycles_per_hour = DummyGauge()
        self.cpu_usage_percent = DummyGauge()
        self.memory_usage_mb = DummyGauge()
        self.options_per_minute = DummyGauge()
    def _record_phase(self, phase, v):
        self._phases[phase] = v


def test_bootstrap_phase_recorded():
    providers = ProvidersBootstrap()
    csv_sink = DummyCsvSink()
    influx = DummyInflux()
    metrics = MetricsBootstrap()
    index_params = { 'NIFTY': { 'enable': True, 'expiries': ['this_week'], 'strikes_itm': 0, 'strikes_otm': 0 } }
    run_unified_collectors(index_params, providers, csv_sink, influx, metrics=metrics, compute_greeks=False, estimate_iv=False)
    assert 'bootstrap' in metrics._phases, 'bootstrap phase missing from metrics observations'
    # bootstrap timing can be very small but should be present (>=0)
    assert metrics._phases['bootstrap'] >= 0.0
