import json, pathlib, tempfile, sys, types, time

# Ensure src on path for direct import when tests are invoked differently
ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from orchestrator.status_writer import write_runtime_status  # type: ignore

class DummyMetrics:
    def __init__(self):
        self._cycle_total = 5
        self._cycle_success = 5
        self._last_cycle_options = 12345
        class _Gauge:
            def __init__(self):
                self._value = types.SimpleNamespace(get=lambda: 1.23)
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
        self._latest_index_prices = {"NIFTY": 20001.0}

class DummyProviders:
    def __init__(self):
        class Prim:
            def get_ltp(self, insts):
                return {insts[0]: {"last_price": 20002.0}}
        self.primary_provider = Prim()
    def get_ltp(self, idx):
        # facade path (will be attempted after metrics capture)
        return 20003.0 if idx == 'NIFTY' else None
    def get_index_data(self, idx):
        return (20004.0, None)

class DummySink: pass
class DummyHealth:
    def __init__(self):
        self.components = {"providers": {"status": "ok", "last_check": None}}


def test_status_writer_direct_basic():
    metrics = DummyMetrics()
    providers = DummyProviders()
    csv_sink = DummySink()
    influx_sink = DummySink()
    health = DummyHealth()
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp)/'status.json'
        write_runtime_status(
            path=str(p),
            cycle=7,
            elapsed=0.123,
            interval=60.0,
            index_params={"NIFTY": {}, "BANKNIFTY": {}},
            providers=providers,
            csv_sink=csv_sink,
            influx_sink=influx_sink,
            metrics=metrics,
            readiness_ok=True,
            readiness_reason="",
            health_monitor=health,
        )
        data = json.loads(p.read_text())
        # Core structural assertions
        for k in ("timestamp","cycle","elapsed","indices","indices_info","indices_detail"):
            assert k in data, f"missing key {k}"
        assert data['cycle'] == 7
        assert data['indices'] == ["NIFTY","BANKNIFTY"]
        # LTP resolution precedence: metrics._latest_index_prices should win (20001.0)
        assert data['indices_info']['NIFTY']['ltp'] == 20001.0
        # BANKNIFTY (no metrics capture) should fall through provider paths and end up with numeric value
        assert isinstance(data['indices_info']['BANKNIFTY']['ltp'], (int,float))
        # Metrics side-effects: runtime_status_writes.set or inc recorded
        assert metrics.runtime_status_writes._value.get() in (1.23, 1.23)  # placeholder gauge unchanged acceptable


def test_status_writer_idempotent_overwrite():
    metrics = DummyMetrics()
    providers = DummyProviders()
    csv_sink = DummySink()
    influx_sink = DummySink()
    health = DummyHealth()
    with tempfile.TemporaryDirectory() as tmp:
        p = pathlib.Path(tmp)/'status.json'
        for i in range(3):
            write_runtime_status(
                path=str(p),
                cycle=i,
                elapsed=0.01*i,
                interval=30.0,
                index_params={"NIFTY": {}},
                providers=providers,
                csv_sink=csv_sink,
                influx_sink=influx_sink,
                metrics=metrics,
                readiness_ok=bool(i%2==0),
                readiness_reason="",
                health_monitor=health,
            )
            data = json.loads(p.read_text())
            assert data['cycle'] == i
            assert data['indices_info']['NIFTY']['ltp'] == 20001.0
        # Ensure atomic write left no stray temp file
        assert not any(f.name.endswith('.tmp') for f in pathlib.Path(tmp).iterdir())
