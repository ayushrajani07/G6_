import datetime
import types

from src.collectors.modules.aggregation_overview import emit_overview_aggregation

class DummySink:
    def __init__(self):
        self.calls = []
    def write_overview_snapshot(self, index_symbol, pcr_snapshot, ts, day_width, *, expected_expiries):
        self.calls.append((index_symbol, pcr_snapshot, ts, day_width, tuple(expected_expiries)))

class DummyCtx:
    def __init__(self, csv_sink=None, influx_sink=None):
        self.csv_sink = csv_sink or DummySink()
        self.influx_sink = influx_sink

class FailingInflux:
    def write_overview_snapshot(self, *a, **k):
        raise RuntimeError("boom")


def test_emit_overview_basic():
    ctx = DummyCtx()
    agg_state = types.SimpleNamespace(representative_day_width=5, snapshot_base_time=None)
    rep_width, base_time = emit_overview_aggregation(
        ctx, 'NIFTY', {'W1': 1.23}, agg_state, datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc), ['this_week']
    )
    assert rep_width == 5
    assert isinstance(base_time, datetime.datetime)
    assert ctx.csv_sink.calls and ctx.csv_sink.calls[0][0] == 'NIFTY'


def test_emit_overview_no_snapshot():
    ctx = DummyCtx()
    agg_state = types.SimpleNamespace(representative_day_width=0, snapshot_base_time=None)
    rep_width, base_time = emit_overview_aggregation(
        ctx, 'BANKNIFTY', None, agg_state, datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc), ['this_week']
    )
    # No write should occur
    assert ctx.csv_sink.calls == []
    assert rep_width == 0
    assert isinstance(base_time, datetime.datetime)


def test_emit_overview_influx_failure_graceful():
    csv = DummySink(); influx = FailingInflux()
    ctx = DummyCtx(csv_sink=csv, influx_sink=influx)
    agg_state = types.SimpleNamespace(representative_day_width=7, snapshot_base_time=None)
    rep_width, base_time = emit_overview_aggregation(
        ctx, 'FINNIFTY', {'W1': 2.34}, agg_state, datetime.datetime(2025,1,1,tzinfo=datetime.timezone.utc), ['this_week','next_week']
    )
    assert rep_width == 7
    # CSV still written once
    assert len(csv.calls) == 1
    assert csv.calls[0][0] == 'FINNIFTY'
