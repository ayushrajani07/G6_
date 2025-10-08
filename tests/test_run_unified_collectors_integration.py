import datetime, time, types
from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.cycle_context import CycleContext  # indirectly ensures import path OK

class FakeProviders:
    def __init__(self):
        self._expiry = datetime.date.today() + datetime.timedelta(days=7)
        self.primary_provider = self  # for synthetic pop compatibility
        self._synth_calls = 0
    def get_expiry_dates(self, index_symbol):
        return [self._expiry]
    def resolve_expiry(self, index_symbol, rule):
        return self._expiry
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        # Create simple instrument dicts
        out = []
        for k in strikes:
            out.append({'strike': k, 'instrument_type':'CE'})
            out.append({'strike': k, 'instrument_type':'PE'})
        return out
    def enrich_with_quotes(self, instruments):
        data = {}
        for inst in instruments:
            k = f"{int(inst['strike'])}{inst['instrument_type']}"
            data[k] = {
                'strike': inst['strike'],
                'instrument_type': inst['instrument_type'],
                'last_price': 10.0,
                'oi': 100,
                'volume': 5,
                'avg_price': 10.0,
            }
        return data
    def get_index_data(self, index_symbol):
        return 20000.0, {'open':19900,'high':20100,'low':19800,'close':20050}
    def get_atm_strike(self, index_symbol):
        return 20000
    def pop_synthetic_quote_usage(self):
        # Simulate zero synthetic count
        self._synth_calls += 1
        return 0, False
    def get_ltp(self, index_symbol):
        return 20000

class DummyCsvSink:
    def __init__(self):
        self.option_batches = []
        self.overview_batches = []
    def write_options_data(self, index_symbol, expiry_date, enriched_data, collection_time, index_price=None, index_ohlc=None, suppress_overview=True, return_metrics=False, expiry_rule_tag=None):
        self.option_batches.append((index_symbol, expiry_date, len(enriched_data)))
        # produce metrics payload
        payload = {
            'expiry_code': 'X1',
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
    def __init__(self): self._value = types.SimpleNamespace(get=lambda: 0)
    def observe(self, v): pass

class Metrics:
    def __init__(self):
        # Basic placeholders for accessed metrics
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
        # Phase metrics
        self.phase_duration_seconds = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(observe=lambda v: None))
        self.phase_failures_total = types.SimpleNamespace(labels=lambda phase: types.SimpleNamespace(inc=lambda : None))
        # API call helper
        def mark_api_call(success, latency_ms): pass
        self.mark_api_call = mark_api_call
        def mark_cycle(success, cycle_seconds, options_processed, option_processing_seconds):
            self._last_cycle_options = options_processed
            self._last_cycle_option_seconds = option_processing_seconds
        self.mark_cycle = mark_cycle
        def mark_index_cycle(index, attempts, failures): pass
        self.mark_index_cycle = mark_index_cycle
        # success rate gauges referenced in cycle summary formatting
        self.collection_success_rate = DummyGauge()
        self.api_success_rate = DummyGauge()
        self.api_response_time = DummyGauge()
        self.cpu_usage_percent = DummyGauge()
        self.memory_usage_mb = DummyGauge()
        self.options_per_minute = DummyGauge()
        # predeclare attributes used by mark_cycle
        self._last_cycle_options = 0
        self._last_cycle_option_seconds = 0.0


def test_run_unified_collectors_end_to_end(monkeypatch):
    # Force market open check bypass (if run_unified_collectors consults is_market_open elsewhere)
    from src.utils.market_hours import is_market_open as real_is_open
    monkeypatch.setattr('src.utils.market_hours.is_market_open', lambda *a, **k: True)

    providers = FakeProviders()
    csv_sink = DummyCsvSink()
    influx_sink = DummyInflux()
    metrics = Metrics()

    index_params = {
        'NIFTY': {
            'enable': True,
            'expiries': ['this_week'],
            'strikes_itm': 1,
            'strikes_otm': 1,
        }
    }

    # Force memory pressure manager neutrality
    monkeypatch.setattr('src.utils.memory_pressure.MemoryPressureManager.evaluate', lambda self: types.SimpleNamespace(name='NORMAL'))
    monkeypatch.setattr('src.utils.memory_pressure.MemoryPressureManager.__init__', lambda self, metrics=None: None)
    run_unified_collectors(index_params, providers, csv_sink, influx_sink, metrics=metrics, compute_greeks=False, estimate_iv=False)

    # Assertions
    # Exactly one options batch persisted
    assert len(csv_sink.option_batches) == 1
    # Each strike produced 2 instruments (CE+PE) -> for itm=1, otm=1 + ATM total strikes=3? Actually _build_strikes adds [atm-1, atm, atm+1]
    # With step=50 or 100 depending on index; NIFTY => step 50, so 3 strikes -> 6 options.
    batch = csv_sink.option_batches[0]
    assert batch[2] >= 6, f"Expected at least 6 options persisted, got {batch[2]}"
    # Overview snapshot written
    assert len(csv_sink.overview_batches) == 1
    # Collection cycle counters incremented
    assert metrics.collection_cycles.v == 1
    # Phase metrics hooks invoked (cannot assert values, just presence of attributes)
    assert hasattr(metrics, '_last_cycle_options')
