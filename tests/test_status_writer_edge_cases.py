import json, pathlib, tempfile, sys, types, os
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orchestrator.status_writer import write_runtime_status  # type: ignore

# ---- Shared dummy classes ----
class DummyMetricsBase:
    def __init__(self):
        class _Gauge:
            def __init__(self):
                self._value = types.SimpleNamespace(get=lambda: 0.0)
            def inc(self):
                pass
            def set(self, v):
                self._value = types.SimpleNamespace(get=lambda: v)
        self.runtime_status_writes = _Gauge()
        self.runtime_status_last_write_unixtime = _Gauge()
        self.options_per_minute = _Gauge()
        self.api_success_rate = _Gauge()
        self.memory_usage_mb = _Gauge()
        self.cpu_usage_percent = _Gauge()
        self._cycle_total = 1
        self._cycle_success = 1
        self._last_cycle_options = 10

class DummyHealth:
    def __init__(self):
        self.components = {"providers": {"status": "ok", "last_check": None}}

# 1. readiness_reason LTP parse fallback
class ProvidersNoData:
    def get_ltp(self, idx):
        return None
    def get_index_data(self, idx):
        raise RuntimeError("no data")

# 2. Synthetic injection (Mock provider name)
class MockPrimary:
    def get_ltp(self, insts):
        return {insts[0]: {"last_price": -1}}  # invalid to force synthetic path
class ProvidersMockWrap:
    def __init__(self):
        self.primary_provider = MockPrimary()
    def get_ltp(self, idx):
        return None
    def get_index_data(self, idx):
        return (0, None)

# 3. File write failure simulation: patch os.replace to raise
class ProvidersMinimal:
    def get_ltp(self, idx):
        return 123.0


def _write_status(tmpdir, **kw):
    path = pathlib.Path(tmpdir)/'status.json'
    write_runtime_status(
        path=str(path),
        cycle=0,
        elapsed=0.0,
        interval=60.0,
        index_params={"NIFTY": {}},
        providers=kw['providers'],
        csv_sink=None,
        influx_sink=None,
        metrics=kw.get('metrics'),
        readiness_ok=True,
        readiness_reason=kw.get('readiness_reason',''),
        health_monitor=DummyHealth(),
    )
    return path


def test_readiness_reason_ltp_parse_fallback():
    metrics = DummyMetricsBase()
    providers = ProvidersNoData()
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_status(tmp, providers=providers, metrics=metrics, readiness_reason="Provider warming LTP=20555 pending")
        data = json.loads(p.read_text())
        assert data['indices_info']['NIFTY']['ltp'] == 20555.0


def test_synthetic_injection_for_mock_provider():
    metrics = DummyMetricsBase()
    providers = ProvidersMockWrap()
    with tempfile.TemporaryDirectory() as tmp:
        p = _write_status(tmp, providers=providers, metrics=metrics)
        data = json.loads(p.read_text())
        # Should use synthetic default for NIFTY (20000.0)
        assert data['indices_info']['NIFTY']['ltp'] == 20000.0


def test_file_write_error_handled(monkeypatch):
    metrics = DummyMetricsBase()
    providers = ProvidersMinimal()
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp)/'status.json'
        # Force os.replace to raise to trigger error handler path
        with mock.patch('orchestrator.status_writer.os.replace', side_effect=OSError('disk error')):
            # Patch error handler to capture invocation
            called = {}
            def fake_handle_error(*a, **k):
                called['ok'] = True
            # Monkeypatch get_error_handler() to return object with handle_error
            import orchestrator.status_writer as sw
            class EH:  # simple stub
                def handle_error(self, *a, **k):
                    fake_handle_error(*a, **k)
            monkeypatch.setattr(sw, 'get_error_handler', lambda: EH())
            write_runtime_status(
                path=str(path),
                cycle=1,
                elapsed=0.01,
                interval=30.0,
                index_params={"NIFTY": {}},
                providers=providers,
                csv_sink=None,
                influx_sink=None,
                metrics=metrics,
                readiness_ok=True,
                readiness_reason="",
                health_monitor=DummyHealth(),
            )
            # File should not exist due to failure
            assert not path.exists()
            assert called.get('ok') is True, 'error handler was not invoked'
