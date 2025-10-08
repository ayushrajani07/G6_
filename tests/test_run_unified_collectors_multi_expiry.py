import datetime, types
from src.collectors.unified_collectors import run_unified_collectors

class FakeProvidersME:
    def __init__(self):
        today = datetime.date.today()
        self._expiries = [today + datetime.timedelta(days=7), today + datetime.timedelta(days=14)]
        self.primary_provider = self
    def get_expiry_dates(self, index_symbol):
        return list(self._expiries)
    def resolve_expiry(self, index_symbol, rule):
        # Map rule positionally for deterministic test
        if rule == 'this_week':
            return self._expiries[0]
        if rule == 'next_week':
            return self._expiries[1]
        return self._expiries[0]
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        out = []
        for k in strikes:
            out.append({'strike': k, 'instrument_type':'CE'})
            out.append({'strike': k, 'instrument_type':'PE'})
        return out
    def enrich_with_quotes(self, instruments):
        data = {}
        for inst in instruments:
            key = f"{int(inst['strike'])}{inst['instrument_type']}"
            data[key] = {
                'strike': inst['strike'],
                'instrument_type': inst['instrument_type'],
                'last_price': 12.0,
                'oi': 200,
                'volume': 9,
                'avg_price': 12.0,
            }
        return data
    def get_index_data(self, index_symbol):
        return 21000.0, {'open':20900,'high':21100,'low':20800,'close':21050}
    def get_atm_strike(self, index_symbol):
        return 21000
    def pop_synthetic_quote_usage(self):
        return 0, False
    def get_ltp(self, index_symbol):
        return 21000

class DummyCsvSink:
    def __init__(self):
        self.option_batches = []
        self.overview_batches = []
    def write_options_data(self, index_symbol, expiry_date, enriched_data, collection_time, index_price=None, index_ohlc=None, suppress_overview=True, return_metrics=False, expiry_rule_tag=None):
        self.option_batches.append((index_symbol, expiry_date, len(enriched_data)))
        payload = {
            'expiry_code': 'ME',
            'pcr': 1.0,
            'timestamp': collection_time,
            'day_width': 5,
        }
        return payload if return_metrics else None
    def write_overview_snapshot(self, index_symbol, pcr_snapshot, snapshot_base_time, representative_day_width, expected_expiries=None):
        self.overview_batches.append((index_symbol, dict(pcr_snapshot)))

class DummyInflux:
    def write_options_data(self, *a, **k):
        pass
    def write_overview_snapshot(self, *a, **k):
        pass

class DummyCounter: 
    def __init__(self): self.v = 0
    def inc(self, n=1): self.v += n

class DummyGauge:
    def __init__(self): self._value = types.SimpleNamespace(get=lambda: self.val)
    def set(self, v): self.val = v

class DummySummary:
    def observe(self, v): pass

class MetricsME:
    def __init__(self):
        self.collection_cycle_in_progress = DummyGauge()
        self.options_collected = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.options_processed_total = DummyCounter()
        self.index_options_processed_total = types.SimpleNamespace(labels=lambda **k: DummyCounter())
        self.pcr = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_price = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_volume = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_oi = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_iv = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_delta = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_gamma = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_theta = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_vega = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.option_rho = types.SimpleNamespace(labels=lambda **k: DummyGauge())
        self.collection_duration = DummySummary()
        self.collection_cycles = DummyCounter()
        self.avg_cycle_time = DummyGauge()
        self.cycles_per_hour = DummyGauge()
        self.phase_duration_seconds = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(observe=lambda v: self._record_phase(phase, v)))
        self.phase_failures_total = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(inc=lambda : None))
        self._phase_observed = set()
        def mark_api_call(success, latency_ms): pass
        self.mark_api_call = mark_api_call
        def mark_cycle(success, cycle_seconds, options_processed, option_processing_seconds): pass
        self.mark_cycle = mark_cycle
        def mark_index_cycle(index, attempts, failures): pass
        self.mark_index_cycle = mark_index_cycle
        self.collection_success_rate = DummyGauge()
        self.api_success_rate = DummyGauge()
        self.api_response_time = DummyGauge()
        self.cpu_usage_percent = DummyGauge()
        self.memory_usage_mb = DummyGauge()
        self.options_per_minute = DummyGauge()
    def _record_phase(self, phase, v):
        if v >= 0:
            self._phase_observed.add(phase)


def test_run_unified_collectors_multi_expiry(monkeypatch):
    # Force market open
    monkeypatch.setattr('src.utils.market_hours.is_market_open', lambda *a, **k: True)
    # Neutral memory pressure
    monkeypatch.setattr('src.utils.memory_pressure.MemoryPressureManager.evaluate', lambda self: types.SimpleNamespace(name='NORMAL'))
    monkeypatch.setattr('src.utils.memory_pressure.MemoryPressureManager.__init__', lambda self, metrics=None: None)

    providers = FakeProvidersME()
    csv_sink = DummyCsvSink()
    influx_sink = DummyInflux()
    metrics = MetricsME()

    index_params = {
        'NIFTY': {
            'enable': True,
            'expiries': ['this_week','next_week'],
            'strikes_itm': 1,
            'strikes_otm': 1,
        }
    }

    run_unified_collectors(index_params, providers, csv_sink, influx_sink, metrics=metrics, compute_greeks=False, estimate_iv=False)

    # Expect two option batches (two expiries)
    assert len(csv_sink.option_batches) == 2, f"Expected 2 option batches, got {len(csv_sink.option_batches)}"
    # Each batch should have at least 6 options (atm-1, atm, atm+1 * 2 calls)
    for batch in csv_sink.option_batches:
        assert batch[2] >= 6
    # Overview snapshot should be written once for consolidated metrics
    assert len(csv_sink.overview_batches) == 1
    # Phase metrics observed for at least one core phase (fetch or enrich etc.)
    assert len(metrics._phase_observed) > 0, 'No phase durations observed'
