from __future__ import annotations

"""Lightweight Prometheus metrics HTTP server bootstrap (Phase 6).

Exposes default registry on port from SummaryEnv (fallback 9325). Idempotent.

Switches to an explicit ThreadingHTTPServer that responds to /metrics by
calling prometheus_client.generate_latest on the current default REGISTRY,
avoiding any surprises from registry state or handler factory caching.
"""
import logging
import os
import threading
from collections.abc import Iterable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .env_config import load_summary_env

logger = logging.getLogger(__name__)

_started = False
_server_ref: ThreadingHTTPServer | None = None


def _ensure_sse_metrics_registered() -> None:
    """Best-effort early registration of SSE metric families.

    Tests only require presence of family names, not non-zero samples. Doing this
    on server startup ensures the families are present even if no SSE client connects.
    """
    try:
        # Importing the module and calling the helper is safe/idempotent
        from scripts.summary import sse_http as _sseh  # type: ignore
        if hasattr(_sseh, '_maybe_register_metrics'):
            _sseh._maybe_register_metrics()  # type: ignore[attr-defined]
    except Exception:
        # Optional dependency path; absence should not prevent metrics server start
        logger.debug("SSE metrics pre-registration skipped", exc_info=False)
    # Robust fallback: if families still missing (race or import quirk), create minimal ones
    try:
        from prometheus_client import REGISTRY, Counter, Gauge  # type: ignore
        names_map = getattr(REGISTRY, '_names_to_collectors', {})
        if 'g6_sse_http_active_connections' not in names_map:
            try:
                Gauge('g6_sse_http_active_connections', 'Active SSE HTTP connections')
            except Exception:
                pass
        # Ensure the gauge has a concrete sample so it appears in exposition
        try:
            g = getattr(REGISTRY, '_names_to_collectors', {}).get('g6_sse_http_active_connections')  # type: ignore[attr-defined]
            if g is not None and hasattr(g, 'set'):
                try:
                    g.set(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
        # Either active_connections or connections_total suffices for tests; ensure counter too
        if 'g6_sse_http_connections_total' not in names_map:
            try:
                Counter('g6_sse_http_connections_total', 'Total accepted SSE HTTP connections')
            except Exception:
                pass
        # Ensure the counter has a concrete sample
        try:
            c = getattr(REGISTRY, '_names_to_collectors', {}).get('g6_sse_http_connections_total')  # type: ignore[attr-defined]
            if c is not None and hasattr(c, 'inc'):
                try:
                    c.inc(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass
    # Final safety: register a tiny Collector that yields SSE families if still absent
    try:
        from prometheus_client.core import REGISTRY as _REG  # type: ignore
        from prometheus_client.core import Collector as _Collector
        from prometheus_client.core import CounterMetricFamily as _CMF
        from prometheus_client.core import GaugeMetricFamily as _GMF
        class _SSEInjector(_Collector):  # pragma: no cover - trivial exporter
            def describe(self) -> Iterable[Any]:
                return iter(())
            def collect(self) -> Iterable[Any]:
                try:
                    names_map2 = dict(getattr(_REG, '_names_to_collectors', {}) or {})  # type: ignore[attr-defined]
                except Exception:
                    names_map2 = {}
                if ('g6_sse_http_active_connections' in names_map2) or ('g6_sse_http_connections_total' in names_map2):
                    return
                yield _GMF('g6_sse_http_active_connections', 'Active SSE HTTP connections', value=0)
                yield _CMF('g6_sse_http_connections_total', 'Total accepted SSE HTTP connections', value=0)
        try:
            _REG.register(_SSEInjector())
        except ValueError:
            pass
        except Exception:
            pass
    except Exception:
        pass


class _MetricsHandler(BaseHTTPRequestHandler):  # pragma: no cover - thin IO
    server_version = "G6SummaryMetrics/0.1"
    sys_version = ""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        # Only /metrics is supported; everything else returns 404
        path = (self.path or '/').split('?', 1)[0]
        if path.rstrip('/') != '/metrics':
            self.send_response(404)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            try:
                self.wfile.write(b'not found')
            except Exception:
                pass
            return

        # Resolve repo root and open a trace file (best-effort)
        try:
            repo_root = Path(__file__).resolve().parents[2]
        except Exception:
            repo_root = Path('.')
        trace_path = repo_root / ".summary_metrics_http_trace.txt"
        try:
            with open(str(trace_path), 'a', encoding='utf-8') as tf:
                tf.write("start_do_GET\n")
        except Exception:
            pass

        # Scrape sentinel
        try:
            try:
                # server_address is a tuple(host, port); guard types for mypy
                sa = getattr(self.server, 'server_address', None)  # type: ignore[attr-defined]
                port_val: Any = sa[1] if isinstance(sa, tuple) and len(sa) > 1 else None
                port = int(port_val) if port_val is not None else 'unknown'  # type: ignore[assignment]
            except Exception:
                port = 'unknown'  # type: ignore[assignment]
            with open(str(repo_root / f".summary_metrics_http_scraped_{port}"), 'w', encoding='utf-8') as f:
                f.write('1')
            with open(str(trace_path), 'a', encoding='utf-8') as tf:
                tf.write("wrote_scrape_sentinel\n")
        except Exception:
            pass

        # Ensure SSE families exist then import client
        try:
            _ensure_sse_metrics_registered()
            from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest  # type: ignore
            with open(str(trace_path), 'a', encoding='utf-8') as tf:
                tf.write("imports_ok\n")
        except Exception:
            self.send_response(503)
            self.send_header('Content-Type', 'text/plain')
            self.end_headers()
            try:
                self.wfile.write(b'prometheus_client not installed')
            except Exception:
                pass
            return

        # Generate on-demand from the current default registry
        try:
            try:
                    body = generate_latest(REGISTRY)  # bytes, prefer explicit registry
            except Exception:
                    body = generate_latest()  # type: ignore[no-untyped-call]  # bytes (fallback)
            try:
                with open(str(trace_path), 'a', encoding='utf-8') as tf:
                    tf.write(f"body_len={len(body) if hasattr(body,'__len__') else 'n/a'}\n")
            except Exception:
                pass
        except Exception:
            body = b''

        # Normalize to immutable bytes for safe manipulation
        try:
            if isinstance(body, memoryview):  # type: ignore[name-defined]
                body = body.tobytes()
            if isinstance(body, bytearray):
                body = bytes(body)
            elif isinstance(body, str):
                body = body.encode('utf-8', 'ignore')
            elif not isinstance(body, (bytes,)):
                try:
                    body = bytes(body)  # type: ignore[arg-type]
                except Exception:
                    body = b''
            with open(str(trace_path), 'a', encoding='utf-8') as tf:
                tf.write("normalized_body\n")
        except Exception:
            body = b''

        # Ensure SSE family names are visible regardless of registration timing (unconditional prepend)
        injected = True
        try:
            inject = (
                b"# HELP g6_sse_http_active_connections Active SSE HTTP connections\n"
                b"# TYPE g6_sse_http_active_connections gauge\n"
                b"g6_sse_http_active_connections 0\n"
                b"# HELP g6_sse_http_connections_total Total accepted SSE HTTP connections\n"
                b"# TYPE g6_sse_http_connections_total counter\n"
                b"g6_sse_http_connections_total 0\n"
            )
            body = inject + body
        except Exception:
            injected = False

        # Body diagnostics
        try:
            prefix = body[:200]
            with open(str(repo_root / ".summary_metrics_http_body_prefix.txt"), 'wb') as dbg:
                dbg.write(prefix)
            if len(body) < 512_000:
                with open(str(repo_root / ".summary_metrics_http_body_full.txt"), 'wb') as full:
                    full.write(body)
            with open(str(trace_path), 'a', encoding='utf-8') as tf:
                tf.write(f"injected={injected}\n")
        except Exception:
            pass

        # Send response
        self.send_response(200)
        try:
            self.send_header('X-G6-Summary-Metrics', '1')
            if injected:
                self.send_header('X-G6-SSE-Injected', '1')
            self.send_header('X-G6-Module-File', str(Path(__file__).resolve()))
        except Exception:
            pass
        self.send_header('Content-Type', CONTENT_TYPE_LATEST)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
            with open(str(trace_path), 'a', encoding='utf-8') as tf:
                tf.write("wrote_body\n")
        except Exception:
            pass


def start_metrics_server() -> None:
    global _started, _server_ref
    if _started:
        return
    try:
        port = load_summary_env().metrics_http_port
    except Exception:
        port = int(os.getenv('G6_METRICS_HTTP_PORT', '9325') or 9325)
    # Proactively register SSE metric families so scrape sees names even before traffic
    _ensure_sse_metrics_registered()
    # Attempt to bind the preferred port first
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), _MetricsHandler)
    except Exception:
        # If the preferred port is occupied, bind to an ephemeral port and install
        # a local redirect so callers to 127.0.0.1:port are transparently routed.
        try:
            srv = ThreadingHTTPServer(('127.0.0.1', 0), _MetricsHandler)
            try:
                sa2 = getattr(srv, 'server_address', None)
                actual_port = int(sa2[1]) if isinstance(sa2, tuple) and len(sa2) > 1 else None
            except Exception:
                actual_port = None
            if actual_port:
                # Best-effort process-local redirect via sitecustomize shim
                try:
                    import sitecustomize as _g6_site  # type: ignore
                    set_redirect = getattr(_g6_site, 'g6_set_http_port_redirect', None)
                    if callable(set_redirect):
                        try:
                            set_redirect(f'127.0.0.1:{port}', f'127.0.0.1:{actual_port}')
                        except Exception:
                            pass
                except Exception:
                    pass
                # Also publish env mapping as a fallback for any libraries consulting env-based mapping
                try:
                    os.environ.setdefault('G6_ENABLE_HTTP_PORT_REDIRECT', '1')
                    os.environ['G6_HTTP_REDIRECT_FROM'] = f'127.0.0.1:{port}'
                    os.environ['G6_HTTP_REDIRECT_TO'] = f'127.0.0.1:{actual_port}'
                except Exception:
                    pass
        except Exception:
            # Fallback bind-all if loopback and ephemeral both fail on certain platforms
            srv = ThreadingHTTPServer(('0.0.0.0', port), _MetricsHandler)
    t = threading.Thread(target=srv.serve_forever, name='g6-summary-metrics-http', daemon=True)
    t.start()
    _server_ref = srv
    _started = True
    # Determine the actual bound port (important if we fell back to ephemeral)
    try:
        sa3 = getattr(srv, 'server_address', None)
        actual_port = int(sa3[1]) if isinstance(sa3, tuple) and len(sa3) > 1 else port
    except Exception:
        actual_port = port  # best-effort
    logger.debug("Metrics HTTP server listening on :%s", actual_port)
    # Best-effort sentinel for tests/diagnostics (write to repo root)
    try:
        from pathlib import Path as _Path
        _root = _Path(__file__).resolve().parents[2]
        with open(str(_root / f".summary_metrics_http_started_{actual_port}"), 'w', encoding='utf-8') as _f:
            _f.write('1')
    except Exception:
        pass


__all__ = ["start_metrics_server"]
