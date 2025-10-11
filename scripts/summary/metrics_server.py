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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


class _MetricsHandler(BaseHTTPRequestHandler):  # pragma: no cover - thin IO
    server_version = "G6SummaryMetrics/0.1"
    sys_version = ""

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
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
        try:
            from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
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
            body = generate_latest()  # bytes
        except Exception:
            body = b''
        self.send_response(200)
        self.send_header('Content-Type', CONTENT_TYPE_LATEST)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
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
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), _MetricsHandler)
    except Exception:
        # Fallback bind-all if loopback fails on certain platforms
        srv = ThreadingHTTPServer(('0.0.0.0', port), _MetricsHandler)
    t = threading.Thread(target=srv.serve_forever, name='g6-summary-metrics-http', daemon=True)
    t.start()
    _server_ref = srv
    _started = True
    logger.debug("Metrics HTTP server listening on :%s", port)


__all__ = ["start_metrics_server"]
