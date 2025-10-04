"""SSE HTTP endpoint (Phase 6 initial implementation).

Provides /summary/events as text/event-stream using the in-process SSEPublisher
plugin's event queue. This MVP polls the publisher's queue snapshot each second
and emits any new events to connected clients.

Planned enhancements (separate todos): auth, IP allow list, rate limiting,
non-blocking queue handoff, graceful shutdown, metrics integration.
"""
from __future__ import annotations
import threading, time, signal, hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import List, Dict, Any, Optional
import os
import json
import logging
try:
    from prometheus_client import Gauge, Counter, Histogram  # type: ignore
except Exception:  # pragma: no cover - dependency optional
    Gauge = Counter = None  # type: ignore

logger = logging.getLogger(__name__)

_publisher_ref = None  # set by unified loop when SSEPublisher instantiated
_lock = threading.RLock()
_shutdown = False
_shutdown_lock = threading.RLock()
_active_connections = 0
_rl_state = {}
_metrics_registered = False
_m_active: Any = None
_m_connects: Any = None
_m_disconnects: Any = None
_m_rejected_conn: Any = None
_m_events_sent: Any = None
_m_events_dropped: Any = None
_m_security_dropped: Any = None  # invalid/sanitized events
_m_auth_fail: Any = None
_m_forbidden_ip: Any = None
_m_rate_limited_conn: Any = None
_m_forbidden_ua: Any = None
_h_event_size: Any = None
_h_event_latency: Any = None
_h_conn_duration: Any = None


def set_publisher(publisher) -> None:  # duck-typed SSEPublisher
    with _lock:
        global _publisher_ref
        _publisher_ref = publisher
        _maybe_register_metrics()


def get_publisher():
    with _lock:
        return _publisher_ref


_ip_conn_window = {}  # ip -> list[timestamps] for connection attempts

# Early stub exports so that modules importing these symbols (e.g., unified_http)
# during partial import states always find them. They will be redefined with full
# implementations later in the file. This guards against edge cases where another
# module performs a from-import before this module finishes executing (rare but
# observed under certain test collection interleavings / tooling reloads).
def _allow_event(handler) -> bool:  # type: ignore[unused-arg]
    return True

def _write_event(handler, evt: Dict[str, Any]) -> None:  # type: ignore[unused-arg]
    try:
        # Minimal best-effort framing (mirrors later full implementation fallback)
        import json as _json
        et = 'message'
        data = None
        if isinstance(evt, dict):
            et = (evt.get('event') or 'message')
            data = evt.get('data')
        payload = ''
        if data is not None:
            try:
                payload = _json.dumps(data, separators=(',',':'))
            except Exception:
                payload = '{}'
        out = f"event: {et}\n" + (f"data: {payload}\n" if payload else '') + "\n"
        handler.wfile.write(out.encode('utf-8'))  # type: ignore[attr-defined]
        handler.wfile.flush()  # type: ignore[attr-defined]
    except Exception:
        pass

def _maybe_register_metrics() -> None:
    global _metrics_registered, _m_active, _m_connects, _m_disconnects, _m_rejected_conn, _m_events_sent, _m_events_dropped, _m_security_dropped, _m_auth_fail, _m_forbidden_ip, _m_rate_limited_conn, _m_forbidden_ua, _h_event_size, _h_event_latency, _h_conn_duration
    if _metrics_registered or Gauge is None or Counter is None:
        return
    try:
        _m_active = Gauge('g6_sse_http_active_connections', 'Active SSE HTTP connections')
        _m_connects = Counter('g6_sse_http_connections_total', 'Total accepted SSE HTTP connections')
        _m_disconnects = Counter('g6_sse_http_disconnects_total', 'Total SSE HTTP disconnects')
        _m_rejected_conn = Counter('g6_sse_http_rejected_connections_total', 'Rejected SSE connections (cap/auth/ip)')
        _m_events_sent = Counter('g6_sse_http_events_sent_total', 'Total SSE events written')
        _m_events_dropped = Counter('g6_sse_http_events_dropped_total', 'Events dropped by rate limiter')
        _m_security_dropped = Counter('g6_sse_http_security_events_dropped_total', 'Events dropped for security/sanitization reasons')
        _m_auth_fail = Counter('g6_sse_http_auth_fail_total', 'Authentication failures (bad/missing token)')
        _m_forbidden_ip = Counter('g6_sse_http_forbidden_ip_total', 'Rejected connections due to IP allow list')
        _m_rate_limited_conn = Counter('g6_sse_http_rate_limited_total', 'Connections rejected due to per-IP rate limiting')
        _m_forbidden_ua = Counter('g6_sse_http_forbidden_ua_total', 'Rejected connections due to User-Agent allow list')
        try:
            _H = Histogram  # type: ignore[name-defined]
        except Exception:  # pragma: no cover - defensive
            _H = None  # type: ignore
        if _H is not None:
            try:
                _h_event_size = _H('g6_sse_http_event_size_bytes', 'Size of SSE events in bytes', buckets=(50,100,250,500,1_000,2_000,4_000,8_000,16_000,32_000,64_000))
                _h_event_latency = _H('g6_sse_http_event_queue_latency_seconds', 'Latency between event enqueue and write', buckets=(0.001,0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.0))
                _h_conn_duration = _H('g6_sse_http_connection_duration_seconds', 'SSE connection lifetime (seconds)', buckets=(1,5,10,30,60,120,300,600,1200))
            except Exception:
                pass
        _metrics_registered = True
    except Exception:
        pass


class SSEHandler(BaseHTTPRequestHandler):  # pragma: no cover (network IO thin wrapper)
    server_version = "G6SSE/0.1"
    sys_version = ""

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _parse_path(self, raw: str) -> str:
        # Reject suspicious characters / path traversal; normalize trailing slash
        if any(ch in raw for ch in ['..', '\\']):
            return ''
        # Basic normalization (strip query for MVP)
        p = raw.split('?',1)[0].strip()
        if not p.startswith('/'):
            p = '/' + p
        return p.rstrip('/')

    def _send_plain(self, code: int, body: str, *, headers: Optional[Dict[str,str]] = None) -> None:
        self.send_response(code)
        self.send_header('Content-Type', 'text/plain')
        if headers:
            for k,v in headers.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body.encode('utf-8'))
        except Exception:
            pass

    def do_GET(self):  # noqa: N802
        path = self._parse_path(self.path or '')
        if path != '/summary/events':
            self.send_error(404, "not found")
            return
        # Centralized security config with optional direct override
        _direct_override = os.getenv('G6_SSE_SECURITY_DIRECT') not in (None, '0', 'false', 'no', 'off')
        if not _direct_override:
            try:
                from scripts.summary.env_config import load_summary_env  # local import
                _env = load_summary_env()
                token_required = _env.sse_token
                allow_ips = set(_env.sse_allow_ips)
                rate_spec = _env.sse_connect_rate_spec or ''
                ua_allow_raw = _env.sse_allow_user_agents
                allow_origin_cfg = _env.sse_allow_origin
            except Exception:
                # Fallback to legacy direct environment reads if SummaryEnv unavailable
                token_required = os.getenv('G6_SSE_API_TOKEN')
                allow_ips = {ip.strip() for ip in (os.getenv('G6_SSE_IP_ALLOW') or '').split(',') if ip.strip()}
                rate_spec = os.getenv('G6_SSE_IP_CONNECT_RATE', '')
                ua_allow_raw = [p for p in (os.getenv('G6_SSE_UA_ALLOW') or '').split(',') if p.strip()]
                allow_origin_cfg = os.getenv('G6_SSE_ALLOW_ORIGIN')
        else:  # explicit legacy path
            token_required = os.getenv('G6_SSE_API_TOKEN')
            allow_ips = {ip.strip() for ip in (os.getenv('G6_SSE_IP_ALLOW') or '').split(',') if ip.strip()}
            rate_spec = os.getenv('G6_SSE_IP_CONNECT_RATE', '')
            ua_allow_raw = [p for p in (os.getenv('G6_SSE_UA_ALLOW') or '').split(',') if p.strip()]
            allow_origin_cfg = os.getenv('G6_SSE_ALLOW_ORIGIN')

        # Auth / ACL checks
        if token_required:
            provided = self.headers.get('X-API-Token')
            if provided != token_required:
                if _m_auth_fail is not None:
                    try: _m_auth_fail.inc()  # type: ignore[attr-defined]
                    except Exception: pass
                self._send_plain(401, 'unauthorized')
                return
        client_ip = self.client_address[0] if isinstance(self.client_address, tuple) else ''
        if allow_ips:
            if client_ip not in allow_ips:
                if _m_forbidden_ip is not None:
                    try: _m_forbidden_ip.inc()  # type: ignore[attr-defined]
                    except Exception: pass
                self._send_plain(403, 'forbidden')
                return
        # --- Security Round 2: per-IP connect rate limiting & UA allow list ---
        if rate_spec:
            # Accept forms like "10/60" or "10:60" meaning 10 connections per 60s window.
            parts = [p for p in rate_spec.replace(':','/').split('/') if p]
            try:
                if len(parts) == 2:
                    max_conn_ip = int(parts[0]); win_sec = int(parts[1])
                elif len(parts) == 1:
                    max_conn_ip = int(parts[0]); win_sec = 60
                else:
                    max_conn_ip = 0; win_sec = 60
            except Exception:
                max_conn_ip = 0; win_sec = 60
            if max_conn_ip > 0 and client_ip:
                now = time.time()
                window = _ip_conn_window.setdefault(client_ip, [])
                # prune old
                cutoff = now - win_sec
                while window and window[0] < cutoff:
                    window.pop(0)
                if len(window) >= max_conn_ip:
                    # rate limited
                    if _m_rate_limited_conn is not None:
                        try: _m_rate_limited_conn.inc()  # type: ignore[attr-defined]
                        except Exception: pass
                    logger.warning("sse_conn reject ip=%s reason=rate_limited attempts=%s/%s window=%ss", client_ip, len(window), max_conn_ip, win_sec)
                    self.send_response(429)
                    self.send_header('Retry-After', '5')
                    self.end_headers()
                    try: self.wfile.write(b'rate limited')
                    except Exception: pass
                    return
                window.append(now)
        # User-Agent allow list enforcement
        ua_allow = ','.join(ua_allow_raw) if ua_allow_raw else ''
        ua = self.headers.get('User-Agent','') or ''
        ua_hash = hashlib.sha256(ua.encode('utf-8')).hexdigest() if ua else ''
        if ua_allow:
            allow_parts = [p.strip() for p in ua_allow.split(',') if p.strip()]
            if allow_parts and not any(part in ua for part in allow_parts):
                if _m_forbidden_ua is not None:
                    try: _m_forbidden_ua.inc()  # type: ignore[attr-defined]
                    except Exception: pass
                logger.warning("sse_conn reject ip=%s reason=forbidden_ua ua_hash=%s", client_ip, ua_hash[:12])
                self._send_plain(403, 'forbidden')
                return
        # Global connection cap
        max_conn = int(os.getenv('G6_SSE_MAX_CONNECTIONS', '50') or 50)
        global _active_connections
        with _lock:
            if _active_connections >= max_conn:
                if _m_rejected_conn is not None:
                    try: _m_rejected_conn.inc()  # type: ignore[attr-defined]
                    except Exception: pass
                self.send_response(429)
                self.send_header('Retry-After', '5')
                self.end_headers()
                try: self.wfile.write(b'too many connections')
                except Exception: pass
                return
            _active_connections += 1
            if _m_connects is not None:
                try: _m_connects.inc()  # type: ignore[attr-defined]
                except Exception: pass
            if _m_active is not None:
                try: _m_active.set(_active_connections)  # type: ignore[attr-defined]
                except Exception: pass
        # connection accepted
        self._conn_start = time.time()
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        req_id = self.headers.get('X-Request-ID')
        if req_id:
            # echo back for correlation (value bounded to 120 safe chars)
            safe_id = ''.join(ch for ch in req_id if ch.isalnum() or ch in ('-','_'))[:120]
            self.send_header('X-Request-ID', safe_id)
        allow_origin = allow_origin_cfg
        if allow_origin:
            self.send_header('Access-Control-Allow-Origin', allow_origin)
        self.end_headers()
        # Simple header flush; avoid large padding hacks (tests now allow time for events)
        try:
            self.wfile.write(b':ok\n\n'); self.wfile.flush()
        except Exception:
            pass
        logger.info("sse_conn accept ip=%s req_id=%s ua_hash=%s", client_ip, req_id or '', ua_hash[:12])
        last_index = 0
        try:
            # Immediate backlog flush (hello/full_snapshot) so first client read gets data
            try:
                _pub_initial = get_publisher()
                if _pub_initial is not None:
                    _initial_events = _pub_initial.events
                    for _evt in _initial_events:
                        try:
                            self._write_event(_evt)
                        except Exception:
                            return
                    last_index = len(_initial_events)
            except Exception:
                pass
            while True:
                pub = get_publisher()
                if pub is None:
                    time.sleep(0.2)
                else:
                    events = pub.events
                    while last_index < len(events):
                        evt = events[last_index]
                        last_index += 1
                        if not self._allow_event():
                            if _m_events_dropped is not None:
                                try: _m_events_dropped.inc()  # type: ignore[attr-defined]
                                except Exception: pass
                            continue
                        try:
                            self._write_event(evt)
                        except Exception:
                            return
                # After attempting to flush backlog, honor shutdown
                with _shutdown_lock:
                    if _shutdown:
                        try:
                            self._write_event({'event':'bye','data':{'reason':'shutdown'}})
                        except Exception:
                            pass
                        break
                time.sleep(0.5)
        except Exception:
            return
        finally:
            with _lock:
                _active_connections = max(0, _active_connections - 1)
                if _m_disconnects is not None:
                    try: _m_disconnects.inc()  # type: ignore[attr-defined]
                    except Exception: pass
                if _m_active is not None:
                    try: _m_active.set(_active_connections)  # type: ignore[attr-defined]
                    except Exception: pass
            try:
                if _h_conn_duration is not None and getattr(self, '_conn_start', None):
                    dur = time.time() - getattr(self, '_conn_start')
                    _h_conn_duration.observe(dur)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _write_event(self, evt: Dict[str, Any]) -> None:
        # Minimal SSE framing: event: <type>\n data: <json>\n\n
        etype_raw = evt.get('event') or 'message'
        # Enforce allowed token chars to prevent control sequences in event name
        etype = ''.join(ch for ch in etype_raw if ch.isalnum() or ch in ('_', '-'))[:40] or 'message'
        data = evt.get('data')
        max_bytes = int(os.getenv('G6_SSE_MAX_EVENT_BYTES', '65536') or 65536)
        try:
            payload = json.dumps(data, separators=(',', ':')) if data is not None else ''
        except Exception:
            payload = '{}'  # fallback
        # Truncate overly large payloads (security / memory guard)
        if len(payload.encode('utf-8')) > max_bytes:
            if _m_security_dropped is not None:
                try: _m_security_dropped.inc()  # type: ignore[attr-defined]
                except Exception: pass
            payload = '{}'  # do not stream original large body
            etype = 'truncated'
        out = f"event: {etype}\n" + (f"data: {payload}\n" if payload else "") + "\n"
        encoded = out.encode('utf-8')
        self.wfile.write(encoded)
        self.wfile.flush()  # ensure immediate delivery for fast tests / small buffers
        try:
            with open(os.path.join('data','panels','_sse_debug_events.log'),'a',encoding='utf-8') as _df:
                _df.write(f"wrote:{etype}\n")
        except Exception:
            pass
        if _m_events_sent is not None:
            try: _m_events_sent.inc()  # type: ignore[attr-defined]
            except Exception: pass
        # advanced metrics
        try:
            if _h_event_size is not None:
                _h_event_size.observe(len(encoded))  # type: ignore[attr-defined]
            if _h_event_latency is not None:
                ts_emit = evt.get('_ts_emit') if isinstance(evt, dict) else None
                if isinstance(ts_emit, (int, float)):
                    _h_event_latency.observe(max(0.0, time.time() - ts_emit))  # type: ignore[attr-defined]
        except Exception:
            pass

    def _allow_event(self) -> bool:
        """Token-bucket style simple limiter per connection.

        G6_SSE_EVENTS_PER_SEC defines max events/sec (burst = that value *2).
        """
        limit = int(os.getenv('G6_SSE_EVENTS_PER_SEC', '100') or 100)
        if limit <= 0:
            return True
        now = time.time()
        state = getattr(self, '_rl', None)
        if state is None:
            # state: (tokens, last_ts)
            state = [limit * 2, now]
            setattr(self, '_rl', state)
        tokens, last = state
        # Refill
        elapsed = now - last
        if elapsed > 0:
            tokens = min(limit * 2, tokens + elapsed * limit)
        if tokens < 1:
            # skip event (could alternatively sleep)
            state[0] = tokens
            state[1] = now
            return False
        tokens -= 1
        state[0] = tokens
        state[1] = now
        return True


def serve_sse_http(port: int = 9320, bind: str = '127.0.0.1', background: bool = True) -> HTTPServer:
    """Start the SSE HTTP server (MVP).

    Uses ThreadingHTTPServer so that additional connection attempts (e.g., those
    expected to be rejected with 429 when the global cap is reached) are not
    blocked behind a long‑lived streaming handler. This fixes test scenarios
    where the second connection previously timed out waiting for the first
    (single-threaded) handler to finish.
    """
    try:
        # Python 3.7+ provides ThreadingHTTPServer directly; fall back to
        # single-threaded only if import fails (should not happen in CI).
        server_cls = ThreadingHTTPServer  # type: ignore[assignment]
    except Exception:  # pragma: no cover - defensive
        server_cls = HTTPServer  # type: ignore[assignment]
    srv = server_cls((bind, port), SSEHandler)
    # If threading mixin is active, ensure threads don't block interpreter exit.
    if hasattr(srv, 'daemon_threads'):
        try: setattr(srv, 'daemon_threads', True)
        except Exception:  # pragma: no cover - defensive
            pass
    # Attach graceful shutdown handler only once (idempotent if called multiple times)
    def _graceful(signum=None, frame=None):  # noqa: D401, ANN001
        global _shutdown
        with _shutdown_lock:
            if _shutdown:
                return
            _shutdown = True
        logger.debug("SSE HTTP shutdown initiated (signal=%s)", signum)
        try:
            srv.shutdown()
        except Exception:
            pass
    for sig in (getattr(signal, 'SIGINT', None), getattr(signal, 'SIGTERM', None)):
        if sig is not None:
            try:
                signal.signal(sig, _graceful)  # type: ignore[arg-type]
            except Exception:
                pass
    if background:
        t = threading.Thread(target=srv.serve_forever, name='g6-sse-http', daemon=True)
        t.start()
    logger.debug("SSE HTTP server listening on %s:%s", bind, port)
    return srv

def initiate_sse_shutdown(reason: str = "requested") -> None:
    """Programmatically trigger SSE shutdown and broadcast bye event (if possible)."""
    global _shutdown
    with _shutdown_lock:
        if _shutdown:
            return
        _shutdown = True
    pub = get_publisher()
    try:
        if pub is not None:
            # Append a synthetic bye event so late pollers / tests see it
            try:
                pub.events.append({'event':'bye','data':{'reason':reason,'ts':time.time()}})
            except Exception:
                pass
    except Exception:
        pass
    logger.debug("SSE shutdown programmatic trigger: %s", reason)

# Compatibility helpers for unified_http: provide module-level _allow_event and
# _write_event that delegate to the underlying SSEHandler implementations.
def _allow_event(handler) -> bool:  # type: ignore[unused-arg]
    try:
        return SSEHandler._allow_event(handler)  # type: ignore[arg-type]
    except Exception:
        return True

def _write_event(handler, evt: Dict[str, Any]) -> None:  # type: ignore[unused-arg]
    """Expose writing logic so unified_http can reuse framing without importing the class.

    Falls back silently if write fails to mirror SSEHandler behavior.
    """
    try:
        # Reuse the method for exact behavior (size limits, metrics etc.).
        SSEHandler._write_event(handler, evt)  # type: ignore[arg-type]
    except Exception:
        try:
            # Very small fallback: best-effort minimal framing
            et = (evt.get('event') if isinstance(evt, dict) else 'message') or 'message'
            data = evt.get('data') if isinstance(evt, dict) else None
            payload = ''
            if data is not None:
                try:
                    payload = json.dumps(data, separators=(',',':'))
                except Exception:
                    payload = '{}'
            out = f"event: {et}\n" + (f"data: {payload}\n" if payload else '') + "\n"
            handler.wfile.write(out.encode('utf-8'))  # type: ignore[attr-defined]
            handler.wfile.flush()  # type: ignore[attr-defined]
        except Exception:
            pass

__all__ = ["serve_sse_http", "set_publisher", "initiate_sse_shutdown", "_allow_event", "_write_event"]
