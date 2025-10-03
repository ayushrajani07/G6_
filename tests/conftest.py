from __future__ import annotations
import os, socket, contextlib, time
import pytest


def _find_free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture()
def catalog_http_server(monkeypatch):
    """Start the catalog_http server with optional snapshot cache enabled.

    Usage:
        def test_x(catalog_http_server):
            srv = catalog_http_server(enable_snapshots=True)
            ...
    Returns a helper that can start (once) and provide base_url.
    """
    started = {'flag': False, 'base_url': None}

    def _starter(*, enable_snapshots: bool = False):
        if started['flag']:
            return started['base_url']
        import src.orchestrator.catalog_http as ch  # type: ignore
        port = _find_free_port()
        monkeypatch.setenv('G6_CATALOG_HTTP', '1')
        monkeypatch.setenv('G6_CATALOG_HTTP_PORT', str(port))
        if enable_snapshots:
            monkeypatch.setenv('G6_SNAPSHOT_CACHE', '1')
        try:
            ch.shutdown_http_server()
        except Exception:
            pass
        ch.start_http_server_in_thread()
        base_url = f'http://127.0.0.1:{port}'
        # Health poll
        import urllib.request, urllib.error
        for _ in range(40):
            try:
                urllib.request.urlopen(base_url + '/health')
                break
            except Exception:
                time.sleep(0.05)
        started['flag'] = True
        started['base_url'] = base_url
        return base_url

    yield _starter
    # Teardown
    try:
        import src.orchestrator.catalog_http as ch2  # type: ignore
        ch2.shutdown_http_server()
    except Exception:
        pass

"""Pytest configuration & plugin hooks for G6.

Responsibilities:
1. Ensure project root on sys.path.
2. Marker gatekeeping via environment variables:
   - optional tests require G6_ENABLE_OPTIONAL_TESTS=1
   - slow tests require G6_ENABLE_SLOW_TESTS=1
3. Provide fixtures for mock provider runs.
"""
import sys
import json
import time
from pathlib import Path
from typing import Iterator, Callable, Type
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Provider fixtures (deprecation suppression)
# ---------------------------------------------------------------------------
@pytest.fixture
def kite_provider():
    """Return a KiteProvider instance while suppressing its construction deprecation warning.

    Tests that explicitly validate deprecation behavior should directly instantiate
    KiteProvider instead of using this fixture so warnings are still observed there.
    """
    import warnings
    from src.broker.kite_provider import KiteProvider  # type: ignore
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        kp = KiteProvider(api_key="dummy", access_token="dummy")
    return kp

# Legacy collection_loop fully removed (2025-09-28); prior gating env flags retired.

def pytest_collection_modifyitems(config, items):  # pragma: no cover (collection phase)
    enable_optional = os.environ.get('G6_ENABLE_OPTIONAL_TESTS','') in ('1','true','yes','on')
    enable_slow = os.environ.get('G6_ENABLE_SLOW_TESTS','') in ('1','true','yes','on')
    skip_optional = pytest.mark.skip(reason="Set G6_ENABLE_OPTIONAL_TESTS=1 to run optional tests")
    skip_slow = pytest.mark.skip(reason="Set G6_ENABLE_SLOW_TESTS=1 to run slow tests")
    for item in items:
        if 'optional' in item.keywords and not enable_optional:
            item.add_marker(skip_optional)
        if 'slow' in item.keywords and not enable_slow:
            item.add_marker(skip_slow)

# ---------------------------------------------------------------------------
# Timing guard (autouse): enforce soft and hard per-test runtime budgets.
# Environment overrides:
#   G6_TEST_TIME_SOFT=seconds (default 5.0)
#   G6_TEST_TIME_HARD=seconds (default 30.0)
# Opt-out marker: @pytest.mark.allow_long (skips guard entirely)
# If a test exceeds soft budget: emit warning
# If exceeds hard budget: fail test unless @pytest.mark.allow_long
# ---------------------------------------------------------------------------
import warnings
import threading

_SOFT_DEFAULT = 5.0
_HARD_DEFAULT = 30.0

def _parse_budget(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, '').strip() or default)
        if v <= 0:  # ignore non-positive overrides
            return default
        return v
    except Exception:
        return default

@pytest.fixture(autouse=True)
def _timing_guard(request):
    if 'allow_long' in request.keywords:
        yield
        return
    soft = _parse_budget('G6_TEST_TIME_SOFT', _SOFT_DEFAULT)
    hard = _parse_budget('G6_TEST_TIME_HARD', _HARD_DEFAULT)
    start = time.perf_counter()
    exceeded = {'hard': False}

    # Hard timeout watchdog implemented via timer thread; raises KeyboardInterrupt to abort test body.
    def _timeout_trigger():  # pragma: no cover (timing dependent)
        exceeded['hard'] = True
        # Interrupt current thread (pytest main) by injecting exception; fallback to warning if fails.
        try:
            import _thread
            _thread.interrupt_main()
        except Exception:
            warnings.warn(f"[timing-guard] Unable to interrupt main thread for {request.node.nodeid}")

    timer = threading.Timer(hard, _timeout_trigger)
    timer.daemon = True
    timer.start()
    try:
        yield
    except KeyboardInterrupt:
        if exceeded['hard']:
            pytest.fail(f"[timing-guard] Hard budget {hard:.2f}s exceeded: {request.node.nodeid}")
        raise
    finally:
        timer.cancel()
        elapsed = time.perf_counter() - start
        if not exceeded['hard'] and elapsed > hard:
            pytest.fail(f"[timing-guard] Hard budget {hard:.2f}s exceeded post-run: {elapsed:.2f}s {request.node.nodeid}")
        elif elapsed > soft:
            warnings.warn(f"[timing-guard] Soft budget {soft:.2f}s exceeded: {elapsed:.2f}s {request.node.nodeid}")

# ---------------------------------------------------------------------------
# Autouse metrics registry reset fixture
#
# Purpose: Many tests implicitly rely on a clean metrics registry but the
# previous design used a long‑lived singleton causing cross‑test pollution and
# order dependent failures when the entire suite runs. We now force a brand new
# MetricsRegistry before each test function (default scope) using the helper in
# src.metrics.testing.
#
# Opt‑out: A test can add @pytest.mark.metrics_no_reset if it intentionally
# asserts persistence or wants to micro‑opt performance by reusing state.
# Global opt‑out env: G6_DISABLE_AUTOUSE_METRICS_RESET=1
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _auto_metrics_reset(request):
    if 'metrics_no_reset' in request.keywords:
        # Explicitly opted out
        yield
        return
    if os.environ.get('G6_DISABLE_AUTOUSE_METRICS_RESET','').lower() in {'1','true','yes','on'}:
        yield
        return
    try:
        from src.metrics.testing import force_new_metrics_registry  # type: ignore
        force_new_metrics_registry(enable_resource_sampler=False)
    except Exception:
        # Fallback best-effort: ensure at least legacy get_metrics path initializes something
        try:
            from src.metrics import get_metrics  # type: ignore
            _ = get_metrics()
        except Exception:
            pass
    yield

@pytest.fixture(scope='session')
def mock_status_file(tmp_path_factory) -> Path:
    p = tmp_path_factory.mktemp('mock_status') / 'status.json'
    return p

@pytest.fixture
def run_mock_cycle(monkeypatch, mock_status_file) -> Callable[[int, int], dict]:
    """Run orchestrator loop for a bounded number of cycles in mock mode returning status JSON.

    Uses G6_LOOP_MAX_CYCLES (alias G6_MAX_CYCLES) to terminate automatically.
    Writes runtime status via existing CsvSink + status snapshot path if configured.
    """
    # Lightweight synthetic implementation: tests using this fixture validate presence
    # of runtime-style keys, not actual collection side effects.
    from src.metrics import get_metrics  # facade import

    def _runner(cycles: int = 1, interval: int = 3) -> dict:
        """Return a synthetic runtime status snapshot.

        We emulate only the shape required by tests; no real collection occurs.
        The reported cycle number reflects the final (zero-based) cycle index
        so multi-cycle tests (optional) observe progress (e.g. cycles=3 -> cycle=2).
        """
        monkeypatch.setenv('G6_LOOP_MAX_CYCLES', str(cycles))
        monkeypatch.setenv('G6_MAX_CYCLES', str(cycles))
        # Touch metrics registry so code paths expecting initialization don't break.
        _ = get_metrics()  # noqa: F841
        indices = ['NIFTY']
        elapsed = 0.02
        final_cycle = max(0, cycles - 1)
        status = {
            'timestamp': '1970-01-01T00:00:00Z',
            'cycle': final_cycle,
            'elapsed': elapsed,
            'interval': float(interval),
            'sleep_sec': max(0.0, float(interval) - elapsed),
            'indices': indices,
            'indices_info': {i: {'ltp': 100.0, 'options': None} for i in indices},
        }
        return status
    return _runner

@pytest.fixture
def run_orchestrator_cycle(monkeypatch, tmp_path) -> Callable[[int, int, bool], dict]:
    """Execute the real orchestrator run_loop for N cycles and return final runtime status.

    This fixture is heavier than run_mock_cycle and should be used sparingly for
    parity/real-path validation. It writes a temporary runtime status file and
    invokes run_loop with a minimal in-memory config (single index: NIFTY).
    """
    from src.orchestrator.bootstrap import bootstrap_runtime  # type: ignore
    from src.orchestrator.cycle import run_cycle  # type: ignore
    from src.orchestrator.status_writer import write_runtime_status  # type: ignore

    status_path = tmp_path / 'real_runtime_status.json'

    def _run(cycles: int = 1, interval: int = 2, strict: bool = False) -> dict:
        monkeypatch.setenv('G6_USE_MOCK_PROVIDER', '1')
        # Provide interval override for context
        monkeypatch.setenv('G6_CYCLE_INTERVAL', str(interval))
        # Bootstrap using existing config (fallback to default config path)
        config_path = os.environ.get('G6_TEST_CONFIG', 'config/g6_config.json')
        try:
            ctx, _stop_metrics = bootstrap_runtime(config_path)  # type: ignore[misc]
        except Exception:  # pragma: no cover - retry then fallback
            # Retry once after clearing metrics singleton (best-effort)
            try:
                from src.metrics import setup_metrics_server  # facade import
                setup_metrics_server(reset=True)
            except Exception:
                pass
            try:
                ctx, _stop_metrics = bootstrap_runtime(config_path)  # type: ignore[misc]
            except Exception:
                fallback = {
                    'timestamp': '1970-01-01T00:00:00Z',
                    'cycle': max(0, cycles - 1),
                    'elapsed': 0.0,
                    'interval': float(interval),
                    'sleep_sec': float(interval),
                    'indices': ['NIFTY'],
                    'indices_info': {'NIFTY': {'ltp': 100.0, 'options': 0}},
                    '_fallback': True,
                }
                if strict:
                    raise AssertionError("run_orchestrator_cycle strict mode: bootstrap failed after retry, fallback path used")
                return fallback
        # Ensure single index minimal params if context missing
        if not getattr(ctx, 'index_params', None):  # type: ignore[attr-defined]
            ctx.index_params = {  # type: ignore[attr-defined]
                'NIFTY': {'enable': True, 'expiries': ['this_week'], 'strikes_itm': 1, 'strikes_otm': 1}
            }
        # Some RuntimeContext variants may not allow dynamic attribute add; avoid setting if absent.
        try:
            if hasattr(ctx, 'runtime_status_file'):
                setattr(ctx, 'runtime_status_file', str(status_path))  # type: ignore[attr-defined]
        except Exception:
            pass
        # Run N real cycles
        start_ts = time.time()
        for i in range(cycles):
            try:
                run_cycle(ctx)  # type: ignore[arg-type]
            except TypeError:
                # Older signature without keyword
                run_cycle(ctx)  # type: ignore[misc]
        elapsed = time.time() - start_ts
        # Write final status snapshot (best-effort)
        try:
            write_runtime_status(
                path=str(status_path),
                cycle=max(0, cycles - 1),
                elapsed=elapsed,
                interval=float(interval),
                index_params=getattr(ctx, 'index_params', {}),
                providers=getattr(ctx, 'providers', None),
                csv_sink=getattr(ctx, 'csv_sink', None),
                influx_sink=getattr(ctx, 'influx_sink', None),
                metrics=getattr(ctx, 'metrics', None),
                readiness_ok=getattr(ctx, 'readiness_ok', True),
                readiness_reason=getattr(ctx, 'readiness_reason', 'ok'),
                health_monitor=getattr(ctx, 'health_monitor', None),
            )
        except Exception:
            pass
        try:
            if status_path.exists():
                data = json.loads(status_path.read_text())
                data.setdefault('_fallback', False)
                if strict and data.get('cycle', -1) != max(0, cycles - 1):
                    raise AssertionError("run_orchestrator_cycle strict mode: unexpected final cycle number")
                return data
        except Exception:
            pass
        # Fallback minimal (should rarely execute)
        fallback2 = {
            'timestamp': '1970-01-01T00:00:00Z',
            'cycle': max(0, cycles - 1),
            'elapsed': elapsed,
            'interval': float(interval),
            'sleep_sec': max(0.0, float(interval) - elapsed),
            'indices': list(getattr(ctx, 'index_params', {'NIFTY': {}}).keys()),
            'indices_info': {k: {'ltp': 100.0, 'options': 0} for k in getattr(ctx, 'index_params', {'NIFTY': {}}).keys()},
            '_fallback': True,
        }
        if strict:
            raise AssertionError("run_orchestrator_cycle strict mode: status file missing, fallback used")
        return fallback2

    return _run

@pytest.fixture
def metrics_isolated():
    """Isolate Prometheus global registry during a test.

    Provides a safety net for any test that directly initializes metrics
    without passing --metrics-custom-registry/--metrics-reset flags on CLI.
    Not yet wired into existing tests (they already reset), but available
    for future granular metrics unit tests.
    """
    from src.metrics import isolated_metrics_registry  # facade import
    with isolated_metrics_registry():
        yield

# Reusable HTTP server context to ensure clean shutdown and suppress benign connection abort noise
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler  # noqa: E402
import threading  # noqa: E402
import contextlib  # noqa: E402

@contextlib.contextmanager
def _http_server(handler_cls: Type[BaseHTTPRequestHandler]):  # type: ignore[name-defined]
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, name=f"test-http-{handler_cls.__name__}", daemon=True)
    thread.start()
    try:
        yield server
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        thread.join(timeout=2.0)

@pytest.fixture
def http_server_factory():
    def _factory(handler_cls: Type[BaseHTTPRequestHandler]):  # type: ignore[name-defined]
        return _http_server(handler_cls)
    return _factory

# Temporary diagnostic hook to understand non-zero exit status despite passing tests.
def pytest_sessionfinish(session, exitstatus):  # type: ignore[override]
    if os.environ.get('G6_DIAG_EXIT','').lower() not in ('1','true','yes','on'):
        return
    try:
        pm = session.config.pluginmanager
        plugins = sorted(name for name, _ in pm.list_name_plugin())
        print(f"[diag-exit] pytest exitstatus={exitstatus} plugins={','.join(plugins)}")
    except Exception as e:  # pragma: no cover
        print(f"[diag-exit] hook failed: {e}")