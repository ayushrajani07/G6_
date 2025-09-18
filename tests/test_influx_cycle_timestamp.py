import datetime as dt
from pathlib import Path

# We import directly from storage.influx_sink
from src.storage.influx_sink import InfluxSink

class _DummyMetrics:
    class _Counter:
        def inc(self):
            pass
    def __init__(self):
        self.influxdb_points_written = self._Counter()

class _CaptureWriteAPI:
    def __init__(self):
        self.captured = []
    def write(self, bucket, record):
        self.captured.append((bucket, record))


def test_cycle_stats_uses_provided_timestamp(monkeypatch):
    # Arrange a sink with dummy client/write api
    sink = InfluxSink.__new__(InfluxSink)  # type: ignore
    # minimal attribute initialization
    object.__setattr__(sink, 'bucket', 'test')
    object.__setattr__(sink, 'max_retries', 1)
    object.__setattr__(sink, 'backoff_base', 0.01)
    object.__setattr__(sink, 'metrics', _DummyMetrics())
    object.__setattr__(sink, 'client', object())  # any truthy object
    capture = _CaptureWriteAPI()
    object.__setattr__(sink, 'write_api', capture)

    provided = dt.datetime(2025, 1, 2, 3, 4, 5, tzinfo=dt.timezone.utc)

    captured_ts = {}
    original_write = capture.write
    def wrapped_write(bucket, record):
        # record should have attribute _time or similar internal; access via __dict__ fallback
        # The official Point exposes 'time' via record._time (private). We attempt both patterns.
        ts = getattr(record, '_time', None)
        if ts is None:
            ts = getattr(record, '_ts', None)
        if ts is not None:
            captured_ts['timestamp'] = ts
        return original_write(bucket, record)
    capture.write = wrapped_write  # type: ignore

    # Act
    sink.write_cycle_stats(
        cycle=7,
        elapsed=0.123,
        success_rate=88.8,
        options_last=42,
        per_index={"NIFTY": 10},
        timestamp=provided,
    )

    # Assert: ensure a record was written and timestamp not replaced
    assert capture.captured, "No record written"
    assert captured_ts.get('timestamp') == provided, "Provided timestamp was not propagated to Point.time()/_time"
