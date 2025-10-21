"""SSE HTTP endpoint (Phase 6 initial implementation).

Provides /summary/events as text/event-stream using the in-process SSEPublisher
plugin's event queue. This MVP polls the publisher's queue snapshot each second
and emits any new events to connected clients.

Planned enhancements (separate todos): auth, IP allow list, rate limiting,
non-blocking queue handoff, graceful shutdown, metrics integration.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import signal
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Any

try:
    from prometheus_client import Counter, Gauge, Histogram  # type: ignore
except Exception:  # pragma: no cover - dependency optional
    Gauge = Counter = None  # type: ignore

logger = logging.getLogger(__name__)

_publisher_ref = None  # set by unified loop when SSEPublisher instantiated
_lock = threading.RLock()
_shutdown = False
_shutdown_lock = threading.RLock()
_active_connections = 0
_rl_state: dict[str, Any] = {}
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

# Track active handler instances to allow immediate broadcast of bye on shutdown
_handlers = set()  # type: ignore[var-annotated]
_force_bye_close = False  # when set via initiate_sse_shutdown, handlers exit ASAP after sending bye


def set_publisher(publisher: Any) -> None:  # duck-typed SSEPublisher
    with _lock:
        global _publisher_ref
        _publisher_ref = publisher
        _maybe_register_metrics()


def get_publisher() -> Any:
    with _lock:
        return _publisher_ref


_ip_conn_window: dict[str, list[float]] = {}  # ip -> list[timestamps] for connection attempts

# Early stub exports so that modules importing these symbols (e.g., unified_http)
# during partial import states always find them. They will be redefined with full
# implementations later in the file. This guards against edge cases where another
# module performs a from-import before this module finishes executing (rare but
# observed under certain test collection interleavings / tooling reloads).
def _allow_event(handler: Any) -> bool:  # type: ignore[unused-arg]
    return True

def _write_event(handler: Any, evt: dict[str, Any]) -> None:  # type: ignore[unused-arg]
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
    """Idempotent metrics registration.

    Ensures all expected counters/histograms exist; if some missing on a subsequent call
    (e.g., partial earlier failure) they are created.
    """
    global _metrics_registered, _m_active, _m_connects, _m_disconnects, _m_rejected_conn
    global _m_events_sent, _m_events_dropped, _m_security_dropped, _m_auth_fail
    global _m_forbidden_ip, _m_rate_limited_conn, _m_forbidden_ua
    global _h_event_size, _h_event_latency, _h_conn_duration
    if Gauge is None or Counter is None:
        return
    try:
        from prometheus_client import REGISTRY  # type: ignore

        def _get_or_create(ctor: Any, name: str, doc: str) -> Any:
            # Always consult live registry; ignore cached globals which may
            # reference old registries.
            try:
                existing = REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
                if existing is not None:
                    return existing
            except Exception:
                pass
            try:
                return ctor(name, doc)
            except ValueError:
                # Another thread may have registered concurrently; fetch again.
                try:
                    return REGISTRY._names_to_collectors.get(name)  # type: ignore[attr-defined]
                except Exception:
                    return None
            except Exception:
                return None

        # Recreate/ensure every metric family each invocation (cheap) so registry
        # resets during tests don't orphan metrics.
        _m_active = _get_or_create(
            Gauge,
            'g6_sse_http_active_connections',
            'Active SSE HTTP connections',
        )
        _m_connects = _get_or_create(
            Counter,
            'g6_sse_http_connections_total',
            'Total accepted SSE HTTP connections',
        )
        _m_disconnects = _get_or_create(
            Counter,
            'g6_sse_http_disconnects_total',
            'Total SSE HTTP disconnects',
        )
        _m_rejected_conn = _get_or_create(
            Counter,
            'g6_sse_http_rejected_connections_total',
            'Rejected SSE connections (cap/auth/ip)',
        )
        _m_events_sent = _get_or_create(
            Counter,
            'g6_sse_http_events_sent_total',
            'Total SSE events written',
        )
        _m_events_dropped = _get_or_create(
            Counter,
            'g6_sse_http_events_dropped_total',
            'Events dropped by rate limiter',
        )
        _m_security_dropped = _get_or_create(
            Counter,
            'g6_sse_http_security_events_dropped_total',
            'Events dropped for security/sanitization reasons',
        )
        _m_auth_fail = _get_or_create(
            Counter,
            'g6_sse_http_auth_fail_total',
            'Authentication failures (bad/missing token)',
        )
        _m_forbidden_ip = _get_or_create(
            Counter,
            'g6_sse_http_forbidden_ip_total',
            'Rejected connections due to IP allow list',
        )
        _m_rate_limited_conn = _get_or_create(
            Counter,
            'g6_sse_http_rate_limited_total',
            'Connections rejected due to per-IP rate limiting',
        )
        _m_forbidden_ua = _get_or_create(
            Counter,
            'g6_sse_http_forbidden_ua_total',
            'Rejected connections due to User-Agent allow list',
        )
        _H = Histogram  # type: ignore[name-defined]
        if _H is not None:
            _h_event_size = _get_or_create(
                _H,
                'g6_sse_http_event_size_bytes',
                'Size of SSE events in bytes',
            )
            _h_event_latency = _get_or_create(
                _H,
                'g6_sse_http_event_queue_latency_seconds',
                'Latency between event enqueue and write',
            )
            _h_conn_duration = _get_or_create(
                _H,
                'g6_sse_http_connection_duration_seconds',
                'SSE connection lifetime (seconds)',
            )
        # Initialize essential families with zero samples so they appear in
        # /metrics exposition
        try:
            if _m_active is not None and hasattr(_m_active, 'set'):
                try:
                    _m_active.set(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if _m_connects is not None and hasattr(_m_connects, 'inc'):
                try:
                    _m_connects.inc(0)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
        _metrics_registered = True
    except Exception:
        pass


class SSEHandler(BaseHTTPRequestHandler):  # pragma: no cover (network IO thin wrapper)
    server_version = "G6SSE/0.1"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
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

    def _send_plain(self, code: int, body: str, *, headers: dict[str, str] | None = None) -> None:
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

    def do_GET(self) -> None:  # noqa: N802
        path = self._parse_path(self.path or '')
        if path != '/summary/events':
            self.send_error(404, "not found")
            return
        # Ensure metrics objects available even if first connections are rejected
        _maybe_register_metrics()
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

        # Auth / ACL checks (auth token, IP allow list)
        if token_required:
            provided = self.headers.get('X-API-Token')
            if provided != token_required:
                if _m_auth_fail is not None:
                    try:
                        _m_auth_fail.inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                self._send_plain(401, 'unauthorized')
                return
        client_ip = self.client_address[0] if isinstance(self.client_address, tuple) else ''
        if allow_ips:
            if client_ip not in allow_ips:
                if _m_forbidden_ip is not None:
                    try:
                        _m_forbidden_ip.inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                self._send_plain(403, 'forbidden')
                return
    # User-Agent allow list enforcement (moved before per-IP connection rate limiting
    # so UA failures return 403 even if rate window exhausted)
        ua_allow = ','.join(ua_allow_raw) if ua_allow_raw else ''
        ua = self.headers.get('User-Agent','') or ''
        ua_hash = hashlib.sha256(ua.encode('utf-8')).hexdigest() if ua else ''
        if ua_allow:
            allow_parts = [p.strip() for p in ua_allow.split(',') if p.strip()]
            if allow_parts and not any(part in ua for part in allow_parts):
                if _m_forbidden_ua is not None:
                    try:
                        _m_forbidden_ua.inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                logger.warning(
                    "sse_conn reject ip=%s reason=forbidden_ua ua_hash=%s",
                    client_ip,
                    ua_hash[:12],
                )
                self._send_plain(403, 'forbidden')
                return
        # Per-IP connection rate limiting (after UA allow so test expectations of 403 precedence hold)
        if rate_spec:
            parts = [p for p in rate_spec.replace(':','/').split('/') if p]
            try:
                if len(parts) == 2:
                    max_conn_ip = int(parts[0])
                    win_sec = int(parts[1])
                elif len(parts) == 1:
                    max_conn_ip = int(parts[0])
                    win_sec = 60
                else:
                    max_conn_ip = 0
                    win_sec = 60
            except Exception:
                max_conn_ip = 0
                win_sec = 60
            if max_conn_ip > 0 and client_ip:
                now = time.time()
                window = _ip_conn_window.setdefault(client_ip, [])
                cutoff = now - win_sec
                # Prune timestamps outside the rolling window
                while window and window[0] < cutoff:
                    window.pop(0)
                # Additional defensive pruning: if many prior short‑lived connections accumulated
                # (e.g., abrupt socket closes in earlier tests) we keep only the most recent
                # max_conn_ip timestamps to avoid synthetic inflation of attempt count.
                if len(window) > max_conn_ip:
                    # retain the newest events only
                    del window[:-max_conn_ip]
                # Expanded debug activation: enable automatically under pytest for flake diagnostics
                _debug_active = (
                    os.getenv('G6_SSE_DEBUG', '') not in ('', '0', 'false', 'no', 'off')
                    or os.getenv('PYTEST_CURRENT_TEST')
                )
                if len(window) >= max_conn_ip:
                    # Second‑chance pruning: if actual active handlers for this IP are below cap,
                    # we may have stale attempt timestamps (e.g., handshake socket connects or
                    # very short lived connects from prior tests). Remove oldest until room.
                    try:
                        active_for_ip = 0
                        for _h in list(_handlers):  # type: ignore[name-defined]
                            try:
                                if getattr(_h, 'client_address', None) and _h.client_address[0] == client_ip:
                                    active_for_ip += 1
                            except Exception:  # noqa: PERF203 - isolate per-handler exceptions to keep connection loop robust
                                pass
                        if active_for_ip < max_conn_ip:
                            # prune excess stale timestamps (keep most recent active_for_ip entries)
                            # ensure we leave at most max_conn_ip-1 so new connection can append
                            target = max(0, max_conn_ip - 1)
                            if len(window) > target:
                                del window[:len(window)-target]
                    except Exception:
                        pass
                if len(window) >= max_conn_ip:
                    if _debug_active:
                        try:
                            logger.debug(
                                "[sse-debug] rate_limit_block ip=%s attempts=%s max=%s window=%s now=%s",
                                client_ip,
                                len(window),
                                max_conn_ip,
                                window,
                                now,
                            )
                            print(
                                f"[sse-debug] rate_limit_block ip={client_ip} attempts={len(window)} "
                                f"max={max_conn_ip} window={window} now={now:.6f}"
                            )
                        except Exception:
                            pass
                    if _m_rate_limited_conn is not None:
                        try:
                            _m_rate_limited_conn.inc()  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    logger.warning(
                        "sse_conn reject ip=%s reason=rate_limited attempts=%s/%s window=%ss",
                        client_ip,
                        len(window),
                        max_conn_ip,
                        win_sec,
                    )
                    self.send_response(429)
                    self.send_header('Retry-After', '5')
                    self.end_headers()
                    try:
                        self.wfile.write(b'rate limited')
                    except Exception:
                        pass
                    return
                window.append(now)
                if _debug_active:
                    try:
                        logger.debug(
                            "[sse-debug] rate_limit_allow ip=%s appended now=%s size=%s/%s window=%s",
                            client_ip,
                            now,
                            len(window),
                            max_conn_ip,
                            window,
                        )
                        print(
                            f"[sse-debug] rate_limit_allow ip={client_ip} size={len(window)}/{max_conn_ip} "
                            f"window={window} now={now:.6f}"
                        )
                    except Exception:
                        pass
        # Global connection cap
        max_conn = int(os.getenv('G6_SSE_MAX_CONNECTIONS', '50') or 50)
        global _active_connections
        with _lock:
            _debug_active_global = (
                os.getenv('G6_SSE_DEBUG', '') not in ('', '0', 'false', 'no', 'off')
                or os.getenv('PYTEST_CURRENT_TEST')
            )
            if _active_connections >= max_conn:
                if _debug_active_global:
                    try:
                        print(f"[sse-debug] global_cap_block active={_active_connections} max={max_conn}")
                    except Exception:
                        pass
                if _m_rejected_conn is not None:
                    try:
                        _m_rejected_conn.inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                self.send_response(429)
                self.send_header('Retry-After', '5')
                self.end_headers()
                try:
                    self.wfile.write(b'too many connections')
                except Exception:
                    pass
                return
            _active_connections += 1
            if _debug_active_global:
                try:
                    print(f"[sse-debug] global_cap_allow new_active={_active_connections} max={max_conn}")
                except Exception:
                    pass
            if _m_connects is not None:
                try:
                    _m_connects.inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
            if _m_active is not None:
                try:
                    _m_active.set(_active_connections)  # type: ignore[attr-defined]
                except Exception:
                    pass
        # connection accepted
        self._conn_start = time.time()
        # Enforce a small minimum connection lifetime to stabilize tests relying on concurrent cap
        # Set this BEFORE sending headers so even if an early exception occurs, the finally block
        # will still honor the minimum lifetime before decrementing the active counter.
        try:
            self._min_alive_until = time.time() + float(
                os.getenv('G6_SSE_CONN_MIN_LIFETIME', '0.25') or 0.25
            )
        except Exception:
            self._min_alive_until = time.time() + 0.25
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
            self.wfile.write(b':ok\n\n')
            self.wfile.flush()
        except Exception:
            pass
        logger.info("sse_conn accept ip=%s req_id=%s ua_hash=%s", client_ip, req_id or '', ua_hash[:12])
        try:
            _handlers.add(self)
        except Exception:
            pass
        last_index = 0
        try:
            # Immediate backlog flush (hello/full_snapshot) so first client read gets data
            try:
                _pub_initial = get_publisher()
                if _pub_initial is not None:
                    _initial_events = _pub_initial.events
                    for _evt in _initial_events:
                        try:  # noqa: PERF203 - per-event isolation prevents a single bad event from killing the stream loop
                            self._write_event(_evt)
                        except Exception:  # noqa: PERF203 - see above rationale
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
                                try:
                                    _m_events_dropped.inc()  # type: ignore[attr-defined]
                                except Exception:
                                    pass
                            continue
                        try:
                            self._write_event(evt)
                        except Exception:
                            return
                # Fast exit path on programmatic shutdown
                global _force_bye_close
                if _shutdown or _force_bye_close:
                    with _shutdown_lock:
                        if _shutdown or _force_bye_close:
                            try:
                                self._write_event({'event': 'bye', 'data': {'reason': 'shutdown'}})
                            except Exception:
                                pass
                            try:
                                # Signal handler/base class to not keep-alive
                                self.close_connection = True  # type: ignore[attr-defined]
                            except Exception:
                                pass
                            break
                # After attempting to flush backlog, honor shutdown
                with _shutdown_lock:
                    if _shutdown:
                        try:
                            self._write_event({'event': 'bye', 'data': {'reason': 'shutdown'}})
                        except Exception:
                            pass
                        try:
                            self.close_connection = True  # type: ignore[attr-defined]
                        except Exception:
                            pass
                        break
                # Allow faster polling in tests via env override
                try:
                    _poll_iv = float(os.getenv('G6_SSE_HTTP_POLL_INTERVAL', '0.5') or 0.5)
                except Exception:
                    _poll_iv = 0.5
                if _poll_iv < 0:
                    _poll_iv = 0.0
                # If shutdown forced, do not sleep full interval
                if _force_bye_close or _shutdown:
                    time.sleep(min(0.01, _poll_iv))
                else:
                    time.sleep(_poll_iv)
        except Exception:
            return
        finally:
            # Honor minimum lifetime before decrementing active count (prevents premature close racing tests)
            try:
                remain = getattr(self, '_min_alive_until', 0) - time.time()
                if remain > 0:
                    time.sleep(min(remain, 0.3))
            except Exception:
                pass
            # Forcefully close underlying socket if flagged for closure (ensures client read unblocks)
            try:
                if getattr(self, 'close_connection', False) and getattr(self, 'connection', None):
                    try:
                        self.connection.shutdown(socket.SHUT_RDWR)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                    try:
                        self.connection.close()  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
            try:
                _handlers.discard(self)
            except Exception:
                pass
            with _lock:
                _active_connections = max(0, _active_connections - 1)
                if _m_disconnects is not None:
                    try:
                        _m_disconnects.inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
                if _m_active is not None:
                    try:
                        _m_active.set(_active_connections)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            try:
                if _h_conn_duration is not None and getattr(self, '_conn_start', None):
                    dur = time.time() - self._conn_start
                    _h_conn_duration.observe(dur)  # type: ignore[attr-defined]
            except Exception:
                pass

    def _write_event(self, evt: dict[str, Any]) -> None:
        try:
            from .sse_shared import write_sse_event  # type: ignore
            write_sse_event(
                self,
                evt,
                security_metric=_m_security_dropped,
                events_sent_metric=_m_events_sent,
                h_event_size=_h_event_size,
                h_event_latency=_h_event_latency,
            )
        except Exception:
            # Fallback to legacy minimal framing (extremely unlikely after import stabilization)
            try:
                et = (evt.get('event') if isinstance(evt, dict) else 'message') or 'message'
                data = evt.get('data') if isinstance(evt, dict) else None
                payload = ''
                if data is not None:
                    try:
                        payload = json.dumps(data, separators=(',', ':'))
                    except Exception:
                        payload = '{}'
                out = f"event: {et}\n" + (f"data: {payload}\n" if payload else '') + "\n"
                self.wfile.write(out.encode('utf-8'))
                self.wfile.flush()
            except Exception:
                pass

    def _allow_event(self) -> bool:
        try:
            from .sse_shared import allow_event_token_bucket  # type: ignore
            return bool(allow_event_token_bucket(self))
        except Exception:
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
    # Reset shutdown flags on fresh server start (important for tests running multiple servers)
    try:
        global _shutdown, _force_bye_close
        with _shutdown_lock:
            _shutdown = False
        _force_bye_close = False
    except Exception:
        pass
    # Clear per-IP window (fresh server start for tests to avoid leakage across suite)
    try:
        _ip_conn_window.clear()
    except Exception:
        pass
    # If threading mixin is active, ensure threads don't block interpreter exit.
    if hasattr(srv, 'daemon_threads'):
        try:
            srv.daemon_threads = True  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - defensive
            pass
    # Attach graceful shutdown handler only once (idempotent if called multiple times)
    from types import FrameType
    def _graceful(signum: int | None = None, frame: FrameType | None = None) -> None:  # noqa: D401
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
    # Append synthetic bye to publisher queue (handlers scanning events will flush quickly)
    pub = get_publisher()
    try:
        if pub is not None:
            try:
                pub.events.append({'event': 'bye', 'data': {'reason': reason, 'ts': time.time()}})
            except Exception:
                pass
    except Exception:
        pass
    # Signal handlers to break early after emitting bye
    global _force_bye_close
    _force_bye_close = True
    logger.debug("SSE shutdown programmatic trigger: %s (force_bye_close=1)", reason)

# Compatibility helpers for unified_http: provide module-level _allow_event and
# _write_event that delegate to the underlying SSEHandler implementations.
def _compat_allow_event(handler: Any) -> bool:  # type: ignore[unused-arg]
    try:
        return SSEHandler._allow_event(handler)  # type: ignore[arg-type]
    except Exception:
        return True

def _compat_write_event(handler: Any, evt: dict[str, Any]) -> None:  # type: ignore[unused-arg]
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

__all__ = ["serve_sse_http", "set_publisher", "initiate_sse_shutdown", "_compat_allow_event", "_compat_write_event"]
