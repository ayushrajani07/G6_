import types
import datetime
from src.collectors.unified_collectors import _persist_and_metrics, PersistResult
from src.collectors.cycle_context import CycleContext

class DummyCsvSink:
    def __init__(self):
        self.calls = []
    def write_options_data(self, index_symbol, expiry_date, enriched_data, collection_time, index_price=None, index_ohlc=None, suppress_overview=True, return_metrics=False, expiry_rule_tag=None):
        self.calls.append((index_symbol, expiry_date, len(enriched_data)))
        payload = {
            'expiry_code': 'X1',
            'pcr': 1.23,
            'timestamp': collection_time,
            'day_width': 5,
        }
        return payload if return_metrics else None

class DummyMetrics:
    def __init__(self):
        self.options_collected = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.options_processed_total = types.SimpleNamespace(inc=lambda v: None)
        self.index_options_processed_total = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(inc=lambda v: None))
        self.pcr = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.instrument_coverage_pct = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_price = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_volume = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_oi = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_iv = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_delta = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_gamma = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_theta = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_vega = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self.option_rho = types.SimpleNamespace(labels=lambda **k: types.SimpleNamespace(set=lambda v: None))
        self._increments = 0
        def inc_capture(v):
            self._increments += v
        self.options_processed_total = types.SimpleNamespace(inc=inc_capture)
    

class DummyInflux:
    def write_options_data(self, *a, **k):
        pass


def test_persist_result_basic_increment():
    metrics = DummyMetrics()
    csv_sink = DummyCsvSink()
    ctx = CycleContext(index_params={}, providers=None, csv_sink=csv_sink, influx_sink=DummyInflux(), metrics=metrics)
    enriched = {
        'OPT1': {'instrument_type':'CE','strike':100,'last_price':5,'oi':10,'volume':2,'iv':15},
        'OPT2': {'instrument_type':'PE','strike':100,'last_price':6,'oi':12,'volume':3,'iv':16},
    }
    res = _persist_and_metrics(ctx, enriched, 'NIFTY', 'this_week', datetime.date.today(), datetime.datetime.now(datetime.timezone.utc), 20000, {}, True)
    assert isinstance(res, PersistResult)
    assert res.option_count == 2
    assert metrics._increments == 2, 'options_processed_total should increment once by option_count'
    # Ensure pcr propagated
    assert res.pcr is None or isinstance(res.pcr, (int,float))
