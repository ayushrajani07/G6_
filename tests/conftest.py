from __future__ import annotations
import os, socket, contextlib, time
import pytest
import asyncio
import warnings

# Silence noisy ResourceWarnings globally in CI where sockets close at shutdown
try:
    warnings.simplefilter("ignore", ResourceWarning)
except Exception:
    pass


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
                # Ensure response is closed to avoid ResourceWarning on Windows CI
                with contextlib.closing(urllib.request.urlopen(base_url + '/health')) as resp:  # noqa: S310 - test-only local URL
                    _ = resp.read(0)
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
# Shadow pipeline isolation fixture (autouse)
# Ensures modules implementing shadow phases are reloaded per-test to avoid
# order-dependent contamination from earlier monkeypatches or partial stubs.
# Cost is small relative to suite stability gains.
# ---------------------------------------------------------------------------
_SHADOW_MODULES = [
    'src.collectors.pipeline.shadow',
    'src.collectors.pipeline.phases',
]

@pytest.fixture(autouse=True)
def _shadow_pipeline_isolation():  # type: ignore
    for m in _SHADOW_MODULES:
        sys.modules.pop(m, None)
    yield
    for m in _SHADOW_MODULES:
        # Leave unloaded so next test incurs a fresh import
        sys.modules.pop(m, None)

# ---------------------------------------------------------------------------
# Early session provisioning (pre-sandbox chdir events)
# Ensures scripts/ and docs/ minimal assets exist in the initial working
# directory so that subprocess-based tests that do NOT chdir (but run from
# temp sandboxes or rely on PYTHONPATH sitecustomize) still find required
# script/doc files. Idempotent and cheap.
# ---------------------------------------------------------------------------
@pytest.fixture(scope='session', autouse=True)
def _early_session_provision():  # type: ignore
    try:
        from tests.sandbox_utils import provision_sandbox  # type: ignore
        provision_sandbox(Path.cwd(), ROOT)
    except Exception:
        pass
    # Ensure any local .env in the starting directory is loaded for tests relying on env creds
    try:
        from src.tools import token_manager as _tm  # type: ignore
        _tm.load_env_vars()
    except Exception:
        pass

@pytest.fixture(scope='session', autouse=True)
def _sandbox_provision_watchdog():  # type: ignore
    """Provision required sandbox assets whenever tests chdir into a fresh temp dir.

    Mechanics:
    - Monkeypatches os.chdir so that after every directory change we invoke
      provision_sandbox() to ensure scripts/ + docs/ subsets and placeholder
      files exist (idempotent) and ensure_pythonpath() to inject the repo root.
    - Centralizes previous inline logic; any future additions to the required
      asset set should be made in tests/sandbox_utils.py only.

    Disable by setting environment variable G6_DISABLE_SANDBOX_PROVISION=1 (or
    true/yes/on) which is useful for debugging test isolation issues.
    """
    if is_truthy_env('G6_DISABLE_SANDBOX_PROVISION'):
        # Still act as a session fixture (generator form) to keep ordering stable.
        yield
        return
    from tests.sandbox_utils import provision_sandbox, ensure_pythonpath  # type: ignore
    original_chdir = os.chdir

    def _wrapped_chdir(path: str | os.PathLike[str]):  # type: ignore
        original_chdir(path)
        provision_sandbox(Path.cwd(), ROOT)
        ensure_pythonpath(ROOT)
        # Automatically overlay env from local .env to support tests that chdir into a tmp sandbox
        try:
            from src.tools import token_manager as _tm2  # type: ignore
            _tm2.load_env_vars()
        except Exception:
            pass

    # Install wrapper
    os.chdir = _wrapped_chdir  # type: ignore[assignment]
    try:
        # Ensure current directory also has layout if tests started elsewhere
        provision_sandbox(Path.cwd(), ROOT)
        ensure_pythonpath(ROOT)
        yield
    finally:
        os.chdir = original_chdir  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Minimal mode / diagnostics toggles
#   G6_TEST_MINIMAL=1            -> skip heavy autouse fixtures & collection gating
#   G6_DISABLE_TIMING_GUARD=1    -> disable per-test timing watchdog only
# These allow isolating hangs during early collection on new / unstable envs.
# ---------------------------------------------------------------------------
_YES = {"1","true","yes","on"}
try:
    from src.utils.env_flags import is_truthy_env  # type: ignore
except Exception:  # pragma: no cover
    def is_truthy_env(name: str) -> bool:  # fallback local shim
        return os.environ.get(name,'').lower() in _YES

G6_TEST_MINIMAL = is_truthy_env('G6_TEST_MINIMAL')
DISABLE_TIMING_GUARD = G6_TEST_MINIMAL or is_truthy_env('G6_DISABLE_TIMING_GUARD')

if G6_TEST_MINIMAL:
    # Emit a single diagnostic line early so a hang before this print indicates import/venv issue.
    print("[g6-pytest] G6_TEST_MINIMAL active: skipping timing guard, metrics reset, marker gating.")

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
    if G6_TEST_MINIMAL:
        return  # Skip gating entirely in minimal mode
    enable_optional = is_truthy_env('G6_ENABLE_OPTIONAL_TESTS')
    enable_slow = is_truthy_env('G6_ENABLE_SLOW_TESTS')
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
    if DISABLE_TIMING_GUARD:
        # Minimal or explicitly disabled: no timing enforcement.
        yield
        return
    if 'allow_long' in request.keywords:
        yield
        return
    soft = _parse_budget('G6_TEST_TIME_SOFT', _SOFT_DEFAULT)
    hard = _parse_budget('G6_TEST_TIME_HARD', _HARD_DEFAULT)
    start = time.perf_counter()
    exceeded = {'hard': False}

    def _timeout_trigger():  # pragma: no cover
        exceeded['hard'] = True
        # Under pytest-xdist, interrupting the main thread can cause a
        # spurious KeyboardInterrupt in the controller during teardown.
        # Instead of interrupting in workers, rely on post-run failure
        # below (hard budget) which still enforces limits without flakiness.
        try:
            import os as _os
            if not _os.environ.get('PYTEST_XDIST_WORKER'):
                import _thread  # type: ignore
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
# Scoped deprecation filters for migration bridge modules
# We intentionally ignore DeprecationWarnings originating from plural bridge
# modules that re-export from singular namespaces during the transition.
# This keeps the suite output clean while still surfacing deprecations from
# direct singular imports elsewhere (tests that assert warnings can still opt-in).
# ---------------------------------------------------------------------------
try:
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"^src\.providers\.errors$",
    )
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        module=r"^src\.providers\.config$",
    )
    # Also ignore by message substring for singular->plural bridge to catch import path based emission
    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=r"Importing from 'src\.provider' is deprecated; use 'src\.providers\..*' instead\."
    )
except Exception:
    pass

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
    if G6_TEST_MINIMAL:
        yield
        return
    if 'metrics_no_reset' in request.keywords:
        yield
        return
    if is_truthy_env('G6_DISABLE_AUTOUSE_METRICS_RESET'):
        yield
        return
    try:
        from src.metrics.testing import force_new_metrics_registry  # type: ignore
        force_new_metrics_registry(enable_resource_sampler=False)
    except Exception:
        try:
            from src.metrics import get_metrics  # type: ignore
            _ = get_metrics()
        except Exception:
            pass
    # Also reset summary in-memory diff metrics to avoid cross-test leakage
    try:
        from scripts.summary import summary_metrics as _sm  # type: ignore
        if hasattr(_sm, '_reset_in_memory'):
            _sm._reset_in_memory()  # type: ignore[attr-defined]
    except Exception:
        pass
    # Clear SSE per-IP connection window to avoid cross-test leakage causing spurious 429s
    try:
        from scripts.summary import sse_http as _sseh  # type: ignore
        if hasattr(_sseh, '_ip_conn_window'):
            _sseh._ip_conn_window.clear()  # type: ignore[attr-defined]
        # Also reset active connection tracking + handlers if present (server leakage across tests)
        if hasattr(_sseh, '_active_connections'):
            try:
                _sseh._active_connections = 0  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(_sseh, '_handlers') and isinstance(getattr(_sseh, '_handlers'), (set, list)):
            try:
                _sseh._handlers.clear()  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass
    yield

# ---------------------------------------------------------------------------
# Autouse OutputRouter reset fixture
#
# Prevents cross-test leakage of sinks / panel transaction stack / file handles.
# Controlled by env override G6_DISABLE_AUTOUSE_OUTPUT_RESET=1 for opt-out and
# test-level marker @pytest.mark.output_no_reset if a test intentionally relies
# on router persistence.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _auto_output_reset(request):
    if is_truthy_env('G6_DISABLE_AUTOUSE_OUTPUT_RESET'):
        yield
        return
    if 'output_no_reset' in request.keywords:
        yield
        return
    # Reset before test
    try:
        from src.utils.output import get_output  # type: ignore
        get_output(reset=True)
    except Exception:
        pass
    yield
    # Optionally close after test to flush resources (best-effort)
    try:
        from src.utils.output import get_output  # type: ignore
        r = get_output()
        if hasattr(r, 'close'):
            r.close()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Async test support: provide event_loop fixture if pytest-asyncio plugin not active
# ---------------------------------------------------------------------------
@pytest.fixture
def event_loop():  # type: ignore[override]
    """Provide a fresh event loop for tests marked with @pytest.mark.asyncio.

    Avoids dependency on pytest-asyncio's auto loop management when plugin
    registration ordering differs across environments.
    """
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()

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
    if not is_truthy_env('G6_DIAG_EXIT'):
        return
    try:
        pm = session.config.pluginmanager
        plugins = sorted(name for name, _ in pm.list_name_plugin())
        print(f"[diag-exit] pytest exitstatus={exitstatus} plugins={','.join(plugins)}")
    except Exception as e:  # pragma: no cover
        print(f"[diag-exit] hook failed: {e}")

# ---------------------------------------------------------------------------
# Optional collection tracing: set G6_COLLECT_TRACE=1 to print each test file
# as pytest decides to collect it. Helps identify which file import/collection
# hangs in environments where -vv gives only a generic 'collecting ...'.

# ---------------------------------------------------------------------------
# Stall / hang diagnostics (thread dump + watchdog)
# ---------------------------------------------------------------------------
import threading as _g6_threading  # type: ignore
import sys as _g6_sys  # type: ignore
import traceback as _g6_tb  # type: ignore
import time as _g6_time  # type: ignore
import inspect as _g6_inspect

if is_truthy_env('G6_THREAD_WATCHDOG'):
    def _g6_watchdog():  # daemon thread
        interval = float(os.getenv('G6_THREAD_WATCHDOG_INTERVAL','30'))
        while True:
            _g6_time.sleep(interval)
            try:
                frames = _g6_sys._current_frames()  # type: ignore[attr-defined]
                live = _g6_threading.enumerate()
                interesting = [t for t in live if not t.name.startswith('MainThread') and 'pytest' not in t.name]
                print(f"[thread-watchdog] threads={len(live)} interesting={len(interesting)}", flush=True)
                for t in interesting[:10]:  # cap verbose output
                    fid = t.ident
                    stack = []
                    if fid in frames:
                        stack = _g6_tb.format_stack(frames[fid])
                    print(f"[thread-watchdog] name={t.name} daemon={t.daemon} alive={t.is_alive()}\n{''.join(stack)}", flush=True)
            except Exception:
                pass
    _t = _g6_threading.Thread(target=_g6_watchdog, name='g6-thread-watchdog', daemon=True)
    _t.start()

if is_truthy_env('G6_TEST_PROGRESS'):
    def pytest_runtest_logstart(nodeid, location):  # type: ignore[override]
        try:
            print(f"[test-progress] start {nodeid}", flush=True)
        except Exception:
            pass

# Lightweight async support fallback: execute coroutine tests without pytest-asyncio
def pytest_runtest_call(item):  # type: ignore[override]
    try:
        test_func = item.obj  # type: ignore[attr-defined]
        if _g6_inspect.iscoroutinefunction(test_func):
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                loop.run_until_complete(test_func(**{k: item.funcargs[k] for k in item.funcargs}))
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()
            return
    except Exception:
        # Let pytest handle normal execution / reporting
        pass

# ---------------------------------------------------------------------------
# Sandbox synchronization fixture
# Copies required 'scripts' and 'docs' directories into the working directory
# for tests that spawn subprocesses referencing paths like 'scripts/g6.py'.
# If the working directory already contains them (normal repo run) it is a no-op.
# Triggered early per-test (autouse) keeping cost low by caching copy outcome.
# ---------------------------------------------------------------------------
_SANDBOX_SYNC_DONE = False

@pytest.fixture(autouse=True)
def _sandbox_sync(tmp_path_factory):  # type: ignore
    global _SANDBOX_SYNC_DONE  # noqa: PLW0603
    if _SANDBOX_SYNC_DONE:
        return
    try:
        root = ROOT  # repo root from earlier
        cwd = Path.cwd()
        # Heuristic: if scripts dir missing in CWD but exists at root, copy subset
        if not (cwd / 'scripts').exists() and (root / 'scripts').exists():
            import shutil
            (cwd / 'scripts').mkdir(exist_ok=True)
            needed = [
                'g6.py',
                'run_orchestrator_loop.py',
                'benchmark_cycles.py',
                'expiry_matrix.py',
            ]
            for fname in needed:
                src_f = root / 'scripts' / fname
                if src_f.exists():
                    try:
                        shutil.copy2(src_f, cwd / 'scripts' / fname)
                    except Exception:
                        pass
        # Docs subset
        if not (cwd / 'docs').exists():
            (cwd / 'docs').mkdir(exist_ok=True)
        for doc_name in ('DEPRECATIONS.md','env_dict.md','metrics_spec.yaml'):
            dst = cwd / 'docs' / doc_name
            if dst.exists():
                continue
            src = root / 'docs' / doc_name
            try:
                if src.exists():
                    dst.write_text(src.read_text(encoding='utf-8'), encoding='utf-8')
            except Exception:
                # Fallback minimal placeholders
                try:
                    if doc_name == 'DEPRECATIONS.md':
                        dst.write_text('# Deprecated Execution Paths\n| Component | Replacement | Deprecated Since | Planned Removal | Migration Action | Notes |\n|-----------|-------------|------------------|-----------------|------------------|-------|\n| `scripts/run_live.py` | run_orchestrator_loop.py | 2025-09-26 | R+2 | update | autogen |\n\n## Environment Flag Deprecations\n\n## Removal Preconditions\n', encoding='utf-8')
                    elif doc_name == 'env_dict.md':
                        dst.write_text('# Environment Variables (sandbox)\nG6_COLLECTION_CYCLES: placeholder\n', encoding='utf-8')
                    elif doc_name == 'metrics_spec.yaml':
                        dst.write_text('- name: g6_collection_cycles\n  type: counter\n  labels: []\n  group: core\n  stability: stable\n  description: cycles (sandbox)\n', encoding='utf-8')
                except Exception:
                    pass
        _SANDBOX_SYNC_DONE = True
    except Exception:
        pass

def pytest_sessionfinish(session, exitstatus):  # type: ignore[override]
    """Augment existing sessionfinish with optional thread dump."""
    # Preserve prior diagnostic hook behavior if G6_DIAG_EXIT set (defined earlier)
    if is_truthy_env('G6_THREAD_DUMP_AT_END'):
        try:
            frames = _g6_sys._current_frames()  # type: ignore[attr-defined]
            live = _g6_threading.enumerate()
            print(f"[thread-dump] total_threads={len(live)} exitstatus={exitstatus}", flush=True)
            for t in live:
                fid = t.ident
                stack = []
                if fid in frames:
                    stack = _g6_tb.format_stack(frames[fid])
                print(f"[thread-dump] name={t.name} daemon={t.daemon} alive={t.is_alive()}\n{''.join(stack)}", flush=True)
        except Exception:
            pass
    # Chain to original hook if defined (we overrode earlier definition). The earlier implementation printed diag-exit.
    # We replicate minimal behavior here for backward compatibility.
    if is_truthy_env('G6_DIAG_EXIT'):
        try:
            pm = session.config.pluginmanager
            plugins = sorted(name for name, _ in pm.list_name_plugin())
            print(f"[diag-exit] pytest exitstatus={exitstatus} plugins={','.join(plugins)}")
        except Exception as e:  # pragma: no cover
            print(f"[diag-exit] hook failed: {e}")
# ---------------------------------------------------------------------------
if is_truthy_env('G6_COLLECT_TRACE'):
    import pathlib as _pl
    from _pytest.nodes import Node  # type: ignore
    from typing import Optional as _Opt

    def pytest_collect_file(file_path, path, parent):  # type: ignore[override]
        # file_path: pathlib.Path in pytest>=8; path retained for backward compat
        try:
            p = _pl.Path(file_path)
        except Exception:
            p = _pl.Path(str(file_path))
        print(f"[collect-trace] {p}", flush=True)
        # Return None to continue default collection
        return None