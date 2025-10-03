import datetime as dt
import types
from dataclasses import dataclass

from src.collectors.cycle_context import ExpiryContext
from src.collectors.modules.persist_flow import run_persist_flow


class DummyCsvSink:
    def __init__(self, fail=False):
        self.fail = fail
        self.allowed_expiry_dates = None
        self._writes = 0
    def write_options_data(self, index_symbol, expiry_date, enriched, collection_time, **kw):
        self._writes += 1
        if self.fail:
            raise IOError("csv fail")
        # minimal metrics payload stub
        return {"pcr": 1.25, "expiry_code": f"{index_symbol}:{expiry_date}", "day_width": 5, "timestamp": collection_time}

class DummyInfluxSink:
    def __init__(self, fail=False):
        self.fail = fail
        self._writes = 0
    def write_options_data(self, *a, **kw):
        self._writes += 1
        if self.fail:
            raise RuntimeError("influx fail")

@dataclass
class MetricsStub:
    def __post_init__(self):
        self.options_collected = types.SimpleNamespace(labels=lambda **kw: types.SimpleNamespace(set=lambda v: None))
        self.options_processed_total = types.SimpleNamespace(inc=lambda v: None)
        self.index_options_processed_total = types.SimpleNamespace(labels=lambda **kw: types.SimpleNamespace(inc=lambda v: None))
        self.pcr = types.SimpleNamespace(labels=lambda **kw: types.SimpleNamespace(set=lambda v: None))
        self.option_price = self.option_volume = self.option_oi = self.option_iv = types.SimpleNamespace(labels=lambda **kw: types.SimpleNamespace(set=lambda v: None))
        self.option_delta = self.option_gamma = self.option_theta = self.option_vega = self.option_rho = types.SimpleNamespace(labels=lambda **kw: types.SimpleNamespace(set=lambda v: None))

class Ctx:
    def __init__(self, csv_sink, influx_sink=None, metrics=None):
        self.csv_sink = csv_sink
        self.influx_sink = influx_sink
        self.metrics = metrics


def _trace(*a, **kw):
    pass


def test_persist_flow_success(monkeypatch):
    enriched = {f"SYM{i}": {"instrument_type": "CE", "oi": 10, "strike": i} for i in range(3)}
    ctx = Ctx(DummyCsvSink(), DummyInfluxSink(), MetricsStub())
    expiry_ctx = ExpiryContext(index_symbol="NIFTY", expiry_rule="this_week", expiry_date=dt.date(2025,1,30), collection_time=dt.datetime.now(dt.timezone.utc), index_price=100.0)
    res = run_persist_flow(ctx, enriched, expiry_ctx, index_ohlc=None, allowed_expiry_dates={expiry_ctx.expiry_date}, trace=_trace, concise_mode=False)
    assert not res.failed
    assert res.option_count == len(enriched)


def test_persist_flow_csv_failure(monkeypatch):
    enriched = {"SYM": {"instrument_type": "CE", "oi": 1, "strike": 1}}
    ctx = Ctx(DummyCsvSink(fail=True), DummyInfluxSink(), MetricsStub())
    expiry_ctx = ExpiryContext(index_symbol="BANKNIFTY", expiry_rule="next_week", expiry_date=dt.date(2025,2,6), collection_time=dt.datetime.now(dt.timezone.utc), index_price=200.0)
    res = run_persist_flow(ctx, enriched, expiry_ctx, index_ohlc=None, allowed_expiry_dates={expiry_ctx.expiry_date}, trace=_trace, concise_mode=True)
    assert res.failed


def test_persist_flow_influx_failure(monkeypatch):
    # Influx failure should not fail overall persist result
    enriched = {"SYM": {"instrument_type": "PE", "oi": 2, "strike": 100}}
    ctx = Ctx(DummyCsvSink(), DummyInfluxSink(fail=True), MetricsStub())
    expiry_ctx = ExpiryContext(index_symbol="FINNIFTY", expiry_rule="this_week", expiry_date=dt.date(2025,3,6), collection_time=dt.datetime.now(dt.timezone.utc), index_price=300.0)
    res = run_persist_flow(ctx, enriched, expiry_ctx, index_ohlc=None, allowed_expiry_dates={expiry_ctx.expiry_date}, trace=_trace, concise_mode=True)
    assert not res.failed


def test_persist_flow_per_option_metrics_off(monkeypatch):
    # When allow_per_option_metrics=False ensure still persists
    enriched = {"SYM": {"instrument_type": "CE", "oi": 5, "strike": 50}}
    ctx = Ctx(DummyCsvSink(), DummyInfluxSink(), MetricsStub())
    expiry_ctx = ExpiryContext(index_symbol="SENSEX", expiry_rule="this_week", expiry_date=dt.date(2025,4,6), collection_time=dt.datetime.now(dt.timezone.utc), index_price=400.0, allow_per_option_metrics=False)
    res = run_persist_flow(ctx, enriched, expiry_ctx, index_ohlc=None, allowed_expiry_dates={expiry_ctx.expiry_date}, trace=_trace, concise_mode=False)
    assert not res.failed
