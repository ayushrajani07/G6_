"""Minimal HTTP handler for /summary/resync and shared snapshot getters.

Kept lightweight to avoid tight coupling with the main loop; tests patch
set_last_snapshot/get_last_snapshot implicitly by importing this module.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from .resync import get_resync_snapshot
from .schema import SCHEMA_VERSION

_last_snapshot: Any | None = None
_lock = threading.RLock()

def set_last_snapshot(snap: Any | None) -> None:  # snap: SummarySnapshot | None (duck-typed to avoid import cycle)
    with _lock:
        global _last_snapshot
        _last_snapshot = snap

def get_last_snapshot() -> Any | None:
    with _lock:
        return _last_snapshot

class ResyncHandler(BaseHTTPRequestHandler):  # pragma: no cover - thin IO layer
    server_version = "G6Resync/0.1"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return  # suppress default noisy logging

    def do_GET(self) -> None:  # noqa: N802
        path = self.path or "/summary/resync"
        if path.rstrip('/') != "/summary/resync":
            self._json(404, {"error": "not found"})
            return
        snap = get_last_snapshot()
        status = getattr(snap, 'status', None) if snap is not None else None
        cycle = getattr(snap, 'cycle', 0) if snap is not None else 0
        domain = getattr(snap, 'domain', None) if snap is not None else None
        hashes = getattr(snap, 'panel_hashes', None) if snap is not None else None
        try:
            payload = get_resync_snapshot(status, cycle=cycle, domain=domain, reuse_hashes=hashes)
        except Exception as e:  # fallback minimal
            payload = {"cycle": cycle, "panels": {}, "error": str(e)}
        payload['schema_version'] = SCHEMA_VERSION
        self._json(200, payload)

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass


def serve_resync(port: int = 9316, *, bind: str = '127.0.0.1', background: bool = True) -> HTTPServer:
    """Start HTTP server for /summary/resync.

    Returns the server instance. If background=True, starts a daemon thread.
    Caller is responsible for updating last snapshot each cycle.
    """
    # Allow env override if caller passed default value
    if port == 9316:
        try:
            from scripts.summary.env_config import load_summary_env
            env_cfg = load_summary_env()
            if env_cfg.resync_http_port:
                port = int(env_cfg.resync_http_port)
        except Exception:
            pass
    server = HTTPServer((bind, port), ResyncHandler)
    if background:
        import threading
        t = threading.Thread(target=server.serve_forever, name='g6-resync-http', daemon=True)
        t.start()
    return server

__all__ = ["set_last_snapshot", "get_last_snapshot", "serve_resync", "ResyncHandler"]
