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
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional

try:
    from .sse_http import get_publisher, _allow_event as _sse_allow_event  # type: ignore
    from .sse_http import _write_event as _sse_write_event  # type: ignore
    from .sse_http import _m_rate_limited_conn, _m_forbidden_ua  # type: ignore
    from .sse_http import _ip_conn_window  # type: ignore
    from .sse_http import initiate_sse_shutdown  # re-export
except Exception:  # pragma: no cover - defensive import race fallback
    # Provide minimal no-op fallbacks so health endpoint still works even if
    # SSE module partially imported (rare test ordering race).
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
from .http_resync import get_last_snapshot
from .resync import get_resync_snapshot
from .schema import SCHEMA_VERSION

try:  # Optional dependency
    from prometheus_client import generate_latest, CONTENT_TYPE_LATEST  # type: ignore
except Exception:  # pragma: no cover
    generate_latest = None  # type: ignore
    CONTENT_TYPE_LATEST = 'text/plain; version=0.0.4; charset=utf-8'

logger = logging.getLogger(__name__)

_shutdown = False
_shutdown_lock = threading.RLock()


class UnifiedSummaryHandler(BaseHTTPRequestHandler):  # pragma: no cover - network IO
    server_version = "G6Summary/0.1"
    sys_version = ""

    def log_message(self, format: str, *args) -> None:  # noqa: A003,D401
        return  # Silence default stderr logging (noise in tests)

    def setup(self) -> None:  # type: ignore[override]
        super().setup()
        try:
            raw = getattr(self, 'wfile', None)
            if raw is not None:
                class _WritableWrapper:  # pragma: no cover - trivial
                    def __init__(self, inner):
                        self._inner = inner
                        self.closed = getattr(inner, 'closed', False)
                    def write(self, data):
                        try:
                            return self._inner.write(data)
                        except Exception:
                            return 0
                    def flush(self):
                        try:
                            self._inner.flush()
                        except Exception:
                            pass
                    def close(self):
                        try:
                            self.closed = True
                            close_fn = getattr(self._inner, 'close', None)
                            if callable(close_fn):
                                close_fn()
                        except Exception:
                            pass
                    def fileno(self):  # Some frameworks inspect fileno
                        try:
                            return self._inner.fileno()  # type: ignore[arg-type]
                        except Exception:
                            return -1
                self.wfile = _WritableWrapper(raw)  # type: ignore
        except Exception:
            pass

    # --- Auth / ACL / rate limiting (trimmed down copy of SSE handler bits) ---
    def _auth_and_acl(self) -> Optional[int]:
        _direct_override = os.getenv('G6_SSE_SECURITY_DIRECT') not in (None, '0', 'false', 'no', 'off')
        if not _direct_override:
            try:
                from scripts.summary.env_config import load_summary_env  # local import
                _env = load_summary_env()
                token_required = _env.sse_token
                allow_ips = set(_env.sse_allow_ips)
                rate_spec = _env.sse_connect_rate_spec or ''
            except Exception:
                token_required = os.getenv('G6_SSE_API_TOKEN')
                allow_ips = {ip.strip() for ip in (os.getenv('G6_SSE_IP_ALLOW') or '').split(',') if ip.strip()}
                rate_spec = os.getenv('G6_SSE_IP_CONNECT_RATE', '')
        else:
            token_required = os.getenv('G6_SSE_API_TOKEN')
            allow_ips = {ip.strip() for ip in (os.getenv('G6_SSE_IP_ALLOW') or '').split(',') if ip.strip()}
            rate_spec = os.getenv('G6_SSE_IP_CONNECT_RATE', '')

        if token_required:
            provided = self.headers.get('X-API-Token')
            if provided != token_required:
                self._plain(401, 'unauthorized')
                return 401
        client_ip = self.client_address[0] if isinstance(self.client_address, tuple) else ''
        if allow_ips:
            if client_ip not in allow_ips:
                self._plain(403, 'forbidden')
                return 403
        # Rate limiting section unchanged except using rate_spec from above
        if rate_spec and client_ip:
            parts = [p for p in rate_spec.replace(':', '/').split('/') if p]
            try:
                if len(parts) == 2:
                    max_conn_ip = int(parts[0]); win_sec = int(parts[1])
                elif len(parts) == 1:
                    max_conn_ip = int(parts[0]); win_sec = 60
                else:
                    max_conn_ip = 0; win_sec = 60
            except Exception:
                max_conn_ip = 0; win_sec = 60
            if max_conn_ip > 0:
                now = time.time()
                window = _ip_conn_window.setdefault(client_ip, [])  # type: ignore
                cutoff = now - win_sec
                while window and window[0] < cutoff:
                    window.pop(0)
                if len(window) >= max_conn_ip:
                    if _m_rate_limited_conn is not None:
                        try: _m_rate_limited_conn.inc()  # type: ignore[attr-defined]
                        except Exception: pass
                    self._plain(429, 'rate limited')
                    return 429
                window.append(now)
        ua_allow = os.getenv('G6_SSE_UA_ALLOW')
        if ua_allow:
            ua = self.headers.get('User-Agent', '') or ''
            allow_parts = [p.strip() for p in ua_allow.split(',') if p.strip()]
            if allow_parts and not any(part in ua for part in allow_parts):
                if _m_forbidden_ua is not None:
                    try: _m_forbidden_ua.inc()  # type: ignore[attr-defined]
                    except Exception: pass
                self._plain(403, 'forbidden')
                return 403
        return None

    # --- Basic response helpers ---
    def _plain(self, code: int, body: str, *, headers: Optional[Dict[str, str]] = None) -> None:
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

    def _json(self, code: int, obj: Dict[str, Any]) -> None:
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
    def do_GET(self):  # noqa: N802
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
            panel_meta = {}
            try:
                if isinstance(status_obj, dict):
                    panel_meta = status_obj.get('panel_push_meta', {}) or {}
            except Exception:
                panel_meta = {}
            diff_stats = panel_meta.get('diff_stats', {}) if isinstance(panel_meta, dict) else {}
            timing_stats = panel_meta.get('timing', {}) if isinstance(panel_meta, dict) else {}
            summary_metrics: Dict[str, Any] = {}
            try:
                from scripts.summary.summary_metrics import snapshot as _metrics_snap  # type: ignore
                summary_metrics = _metrics_snap()
            except Exception:
                pass
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
            adaptive = {}
            try:
                if 'gauge' in summary_metrics and 'g6_adaptive_backlog_ratio' in summary_metrics.get('gauge', {}):
                    adaptive['backlog_ratio'] = summary_metrics['gauge']['g6_adaptive_backlog_ratio']  # type: ignore[index]
            except Exception:
                pass
            health_payload = {
                'ok': True,
                'cycle': cycle,
                'schema_version': SCHEMA_VERSION,
                'diff': diff_stats,
                'panel_updates_last': summary_metrics.get('gauge', {}).get('g6_summary_panel_updates_last') if isinstance(summary_metrics.get('gauge'), dict) else None,
                'hit_ratio': summary_metrics.get('gauge', {}).get('g6_summary_diff_hit_ratio') if isinstance(summary_metrics.get('gauge'), dict) else None,
                'churn_ratio': summary_metrics.get('gauge', {}).get('g6_summary_panel_churn_ratio') if isinstance(summary_metrics.get('gauge'), dict) else None,
                'high_churn_streak': summary_metrics.get('gauge', {}).get('g6_summary_panel_high_churn_streak') if isinstance(summary_metrics.get('gauge'), dict) else None,
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


def serve_unified_http(port: int = 9329, bind: str = '127.0.0.1', background: bool = True) -> HTTPServer:
    srv = HTTPServer((bind, port), UnifiedSummaryHandler)
    if background:
        t = threading.Thread(target=srv.serve_forever, name='g6-summary-unified-http', daemon=True)
        t.start()
    logger.debug("Unified summary HTTP server listening on %s:%s", bind, port)
    return srv

__all__ = [
    'serve_unified_http',
    'initiate_sse_shutdown',
]
