"""Unified unified HTTP server for summary subsystem (clean implementation).

This file was reconstructed to resolve earlier patch corruption. It offers:
  * /summary/events  (SSE stream)
  * /summary/resync  (snapshot with hashes)
  * /summary/health  (enhanced JSON health/metrics)
  * /metrics         (Prometheus exposition)

Test friendliness: ``setup`` wraps ``wfile`` so tests can monkeypatch
``handler.wfile.write`` and capture response bodies.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

try:
    from .sse_http import (
        _allow_event as _sse_allow_event,  # type: ignore
    )
    from .sse_http import (
        _ip_conn_window,
        _m_forbidden_ua,
        _m_rate_limited_conn,
        get_publisher,
        initiate_sse_shutdown,  # re-export
    )  # type: ignore
    from .sse_http import (
        _write_event as _sse_write_event,  # type: ignore
    )
except Exception:  # pragma: no cover - defensive import race fallback
    def _sse_allow_event(_handler):  # type: ignore
        return True
    def _sse_write_event(_handler, _evt):  # type: ignore
        return None
    def get_publisher():  # type: ignore
        return None
    _m_rate_limited_conn = _m_forbidden_ua = None  # type: ignore
    _ip_conn_window = {}
    def initiate_sse_shutdown(*_a, **_kw):  # type: ignore
        return None

# New shared security / rate limiting helper (extracted from sse_http & prior inline copy)
try:
    from .sse_shared import enforce_auth_and_rate, load_security_config  # type: ignore
except Exception:  # pragma: no cover - if import fails we fallback to legacy inline path
    load_security_config = enforce_auth_and_rate = None  # type: ignore
from .http_resync import get_last_snapshot
from .resync import get_resync_snapshot
from .schema import SCHEMA_VERSION

try:  # Optional dependency
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest  # type: ignore
except Exception:  # pragma: no cover
    generate_latest = None  # type: ignore
    CONTENT_TYPE_LATEST = 'text/plain; version=0.0.4; charset=utf-8'

logger = logging.getLogger(__name__)

# Improve fast test reliability: allow quick port reuse between runs
try:
    ThreadingHTTPServer.allow_reuse_address = True  # type: ignore[attr-defined]
except Exception:
    pass

_shutdown = False
_shutdown_lock = threading.RLock()


class UnifiedSummaryHandler(BaseHTTPRequestHandler):  # pragma: no cover - network IO
    server_version = "G6Summary/0.1"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003,D401
        return  # Silence default stderr logging (noise in tests)

    def setup(self) -> None:  # type: ignore[override]
        super().setup()
        try:
            raw = getattr(self, 'wfile', None)
            if raw is not None:
                class _WritableWrapper:  # pragma: no cover - trivial
                    def __init__(self, inner: Any) -> None:
                        self._inner: Any = inner
                        self.closed: bool = bool(getattr(inner, 'closed', False))
                    def write(self, data: bytes) -> int:
                        try:
                            # Most streams: write(bytes) -> int
                            return int(self._inner.write(data))  # type: ignore[no-any-return]
                        except Exception:
                            return 0
                    def flush(self) -> None:
                        try:
                            self._inner.flush()
                        except Exception:
                            pass
                    def close(self) -> None:
                        try:
                            self.closed = True
                            close_fn = getattr(self._inner, 'close', None)
                            if callable(close_fn):
                                close_fn()
                        except Exception:
                            pass
                    def fileno(self) -> int:  # Some frameworks inspect fileno
                        try:
                            return int(self._inner.fileno())  # type: ignore[no-any-return]
                        except Exception:
                            return -1
                self.wfile = _WritableWrapper(raw)  # type: ignore
        except Exception:
            pass

    # --- Auth / ACL / rate limiting (delegated to shared helper) ---
    def _auth_and_acl(self) -> int | None:
        # Use explicit None checks to satisfy type checker and avoid truthy-function warnings
        cfg_fn = load_security_config
        enforce = enforce_auth_and_rate
        if (cfg_fn is not None) and (enforce is not None):
            cfg = cfg_fn()
            # Provide metrics mapping (only those used during rejection paths)
            metrics_map = {
                'forbidden_ua': _m_forbidden_ua,
                'rate_limited_conn': _m_rate_limited_conn,
            }
            # Attempt to import handler set for second-chance pruning; tolerate failure
            handlers_ref = None
            try:
                from scripts.summary import sse_http as _sseh  # type: ignore
                handlers_ref = getattr(_sseh, '_handlers', None)
            except Exception:
                pass
            code = enforce(
                self,
                cfg,
                ip_conn_window=_ip_conn_window,  # type: ignore
                handlers_ref=handlers_ref,  # type: ignore[arg-type]
                metrics=metrics_map,
            )
            return code
        # Fallback to permissive if helper unavailable (matches previous defensive path)
        return None

    # --- Basic response helpers ---
    def _plain(self, code: int, body: str, *, headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        if headers:
            for k, v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body.encode('utf-8'))
        except Exception:
            pass

    def _json(self, code: int, obj: dict[str, Any]) -> None:
        body = json.dumps(obj, separators=(',', ':')).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        try:
            writer = getattr(getattr(self, 'wfile', None), 'write', None)
            if callable(writer):
                try:
                    writer(body)  # Common case: single-arg write(data)
                except TypeError:
                    # Test monkeypatch pattern may assign a raw function def write(self,data)
                    try:
                        writer(self.wfile, body)  # type: ignore[misc]
                    except Exception:
                        pass
            # Store for any future diagnostics/tests
            try:
                self._last_json_body = body  # type: ignore[attr-defined]
            except Exception:
                pass
        except Exception:
            pass

    # --- Handlers ---
    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or '/').split('?', 1)[0].rstrip('/')
        if path == '':
            path = '/'
        if path == '/summary/events':
            code = self._auth_and_acl()
            if code is not None:
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            req_id = self.headers.get('X-Request-ID')
            if req_id:
                safe_id = ''.join(ch for ch in req_id if ch.isalnum() or ch in ('-', '_'))[:120]
                self.send_header('X-Request-ID', safe_id)
            allow_origin = os.getenv('G6_SSE_ALLOW_ORIGIN')
            if allow_origin:
                self.send_header('Access-Control-Allow-Origin', allow_origin)
            self.end_headers()
            last_index = 0
            try:
                while True:
                    with _shutdown_lock:
                        if _shutdown:
                            try:
                                _sse_write_event(self, {'event': 'bye', 'data': {'reason': 'shutdown'}})  # type: ignore[arg-type]
                            except Exception:
                                pass
                            break
                    pub = get_publisher()
                    if pub is None:
                        time.sleep(0.5)
                        continue
                    events = pub.events
                    while last_index < len(events):
                        evt = events[last_index]
                        last_index += 1
                        if not _sse_allow_event(self):  # type: ignore[arg-type]
                            continue
                        try:
                            _sse_write_event(self, evt)  # type: ignore[arg-type]
                        except Exception:
                            return
                    time.sleep(1.0)
            except Exception:
                return
            return
        if path == '/summary/resync':
            snap = get_last_snapshot()
            status = getattr(snap, 'status', None) if snap is not None else None
            cycle = getattr(snap, 'cycle', 0) if snap is not None else 0
            domain = getattr(snap, 'domain', None) if snap is not None else None
            hashes = getattr(snap, 'panel_hashes', None) if snap is not None else None
            try:
                payload = get_resync_snapshot(status, cycle=cycle, domain=domain, reuse_hashes=hashes)
            except Exception as e:  # noqa: BLE001
                payload = {'cycle': cycle, 'panels': {}, 'error': str(e)}
            payload['schema_version'] = SCHEMA_VERSION
            self._json(200, payload)
            return
        if path == '/summary/health':
            snap = get_last_snapshot()
            cycle = getattr(snap, 'cycle', 0) if snap is not None else 0
            status_obj = getattr(snap, 'status', {}) if snap is not None else {}
            panel_meta: dict[str, Any] = {}
            try:
                if isinstance(status_obj, dict):
                    panel_meta = status_obj.get('panel_push_meta', {}) or {}
            except Exception:
                panel_meta = {}
            diff_stats = panel_meta.get('diff_stats', {}) if isinstance(panel_meta, dict) else {}
            timing_stats = panel_meta.get('timing', {}) if isinstance(panel_meta, dict) else {}
            # Import lightweight metrics snapshot to enrich fields used by tests
            summary_metrics: dict[str, Any] = {}
            sse_state = {}
            try:
                from .sse_state import get_sse_state  # type: ignore
                st = get_sse_state()
                if st is not None:
                    sse_state = {
                        'clients': getattr(st, 'clients', 0),
                        'events_sent': getattr(st, 'events_sent', 0),
                        'last_connect_unixtime': getattr(st, 'last_connect_unixtime', None),
                    }
            except Exception:
                pass
            # Attempt to take a point-in-time snapshot from summary_metrics
            try:
                from . import summary_metrics as sm  # type: ignore
                snap = sm.snapshot()  # returns { 'gauge': { ... }, 'counter': {...} }
                if isinstance(snap, dict):
                    summary_metrics = snap
            except Exception:
                summary_metrics = {}
            adaptive = {}
            try:
                if 'gauge' in summary_metrics and 'g6_adaptive_backlog_ratio' in summary_metrics.get('gauge', {}):
                    adaptive['backlog_ratio'] = summary_metrics['gauge']['g6_adaptive_backlog_ratio']  # type: ignore[index]
            except Exception:
                pass
            # Pull enriched gauges if available
            gauges = summary_metrics.get('gauge', {}) if isinstance(summary_metrics, dict) else {}
            panel_updates_last = gauges.get('g6_summary_panel_updates_last') if isinstance(gauges, dict) else None
            hit_ratio_g = gauges.get('g6_summary_diff_hit_ratio') if isinstance(gauges, dict) else None
            churn_ratio = gauges.get('g6_summary_panel_churn_ratio') if isinstance(gauges, dict) else None
            high_churn_streak = gauges.get('g6_summary_panel_high_churn_streak') if isinstance(gauges, dict) else None

            health_payload = {
                'ok': True,
                'cycle': cycle,
                'schema_version': SCHEMA_VERSION,
                'diff': diff_stats,
                'panel_updates_last': panel_updates_last,
                'hit_ratio': (
                    diff_stats.get('hit_ratio')
                    if isinstance(diff_stats, dict) and 'hit_ratio' in diff_stats
                    else hit_ratio_g
                ),
                'churn_ratio': churn_ratio,
                'high_churn_streak': high_churn_streak,
                'timing': timing_stats,
                'sse': sse_state,
                'adaptive': adaptive,
            }
            self._json(200, health_payload)
            return
        if path == '/metrics':
            if generate_latest is None:
                self._plain(503, 'prometheus_client not installed')
                return
            try:
                output = generate_latest()  # bytes
            except Exception:
                output = b''  # pragma: no cover
            self.send_response(200)
            self.send_header('Content-Type', CONTENT_TYPE_LATEST)
            self.send_header('Content-Length', str(len(output)))
            self.end_headers()
            try:
                if output:
                    self.wfile.write(output)
            except Exception:
                pass
            return
        self._json(404, {'error': 'not found'})


def serve_unified_http(port: int = 9329, bind: str = '127.0.0.1', background: bool = True) -> ThreadingHTTPServer:
    try:
        srv = ThreadingHTTPServer((bind, port), UnifiedSummaryHandler)
    except Exception:
        # Fallback: bind all interfaces if loopback fails unexpectedly on some platforms
        srv = ThreadingHTTPServer(('0.0.0.0', port), UnifiedSummaryHandler)
    if background:
        t = threading.Thread(target=srv.serve_forever, name='g6-summary-unified-http', daemon=True)
        t.start()
    logger.debug("Unified summary HTTP server listening on %s:%s", bind, port)
    try:
        # Best-effort sentinel to aid tests/diagnostics
        with open(f".unified_http_started_{port}", 'w', encoding='utf-8') as _f:
            _f.write(str(time.time()))
    except Exception:
        pass
    return srv

__all__ = [
    'serve_unified_http',
    'initiate_sse_shutdown',
]
