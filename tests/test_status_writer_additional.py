import json, pathlib, tempfile, sys, types

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orchestrator.status_writer import write_runtime_status  # type: ignore

class Gauge:
    def __init__(self, initial=0.0):
        self._value = types.SimpleNamespace(get=lambda: initial)
        self._count = 0
    def inc(self):
        self._count += 1
    def set(self, v):
        self._value = types.SimpleNamespace(get=lambda: v)

class MetricsForEffects:
    def __init__(self):
        self._cycle_total = 2
        self._cycle_success = 2
        self._last_cycle_options = 42
        self.runtime_status_writes = Gauge()
        self.runtime_status_last_write_unixtime = Gauge()
        self.options_per_minute = Gauge(5.0)
        self.api_success_rate = Gauge(0.99)
        self.memory_usage_mb = Gauge(123.0)
        self.cpu_usage_percent = Gauge(7.5)
        self._latest_index_prices = {"NIFTY": 21000.5}

class ProvidersDirectQuoteFallback:
    def __init__(self):
        class Prim:
            def get_ltp(self, insts):
                return {insts[0]: {"last_price": -1}}  # invalid
            def get_quote(self, insts):
                return {insts[0]: {"last_price": 21111.0}}
        self.primary_provider = Prim()
    def get_ltp(self, idx):
        return None
    def get_index_data(self, idx):
        return (0, None)

class DummyHealth:
    def __init__(self):
        self.components = {}


def test_direct_quote_fallback_path():
    metrics = MetricsForEffects()
    providers = ProvidersDirectQuoteFallback()
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp)/'status.json'
        write_runtime_status(
            path=str(p),
            cycle=3,
            elapsed=0.2,
            interval=60.0,
            index_params={"NIFTY": {}},
            providers=providers,
            csv_sink=None,
            influx_sink=None,
            metrics=metrics,
            readiness_ok=True,
            readiness_reason="",
            health_monitor=DummyHealth(),
        )
        data = json.loads(p.read_text())
        # metrics capture should win (21000.5) before quote fallback
        assert data['indices_info']['NIFTY']['ltp'] == 21000.5


def test_empty_indices_params_graceful():
    metrics = MetricsForEffects()
    providers = ProvidersDirectQuoteFallback()
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp)/'status.json'
        write_runtime_status(
            path=str(p),
            cycle=0,
            elapsed=0.0,
            interval=10.0,
            index_params={},
            providers=providers,
            csv_sink=None,
            influx_sink=None,
            metrics=metrics,
            readiness_ok=None,
            readiness_reason="",
            health_monitor=DummyHealth(),
        )
        data = json.loads(p.read_text())
        assert data['indices'] == []
        assert data['indices_info'] == {}
        assert data['readiness_ok'] is None


def test_metrics_side_effects_written():
    metrics = MetricsForEffects()
    providers = ProvidersDirectQuoteFallback()
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp)/'status.json'
        write_runtime_status(
            path=str(p),
            cycle=5,
            elapsed=0.05,
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
        # runtime_status_writes.inc() should have been called once
        assert metrics.runtime_status_writes._count == 1
        # last write unixtime gauge should have been set (value not default 0.0)
        assert metrics.runtime_status_last_write_unixtime._value.get() != 0.0
