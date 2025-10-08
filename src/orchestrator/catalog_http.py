"""Lightweight HTTP endpoint exposing catalog JSON for dashboards.

Environment:
  G6_CATALOG_HTTP=1            -> enable server (started in a background thread by bootstrap integration TBD)
  G6_CATALOG_HTTP_HOST=0.0.0.0 -> bind host (default 127.0.0.1)
  G6_CATALOG_HTTP_PORT=9315    -> port (default 9315)
  G6_CATALOG_HTTP_REBUILD=1    -> rebuild catalog on each request (else serve last emitted file if present)

Routes:
  GET /catalog        -> JSON catalog (builds if missing or rebuild toggle on)
    GET /health         -> simple JSON ok indicator
    GET /snapshots      -> JSON snapshot cache (if enabled) optional ?index=INDEX

Design goals:
  * Zero external deps (uses http.server)
  * Non-blocking to main loop (daemon thread)
  * Graceful failure logging if bind fails
"""
from __future__ import annotations

import json, os, threading, logging, time, hashlib, gzip, io
from src.utils.env_flags import is_truthy_env  # type: ignore
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from typing import Optional
from pathlib import Path
import base64

from .catalog import build_catalog, CATALOG_PATH

try:  # Optional dependency to keep bootstrap lightweight when events unused
    from src.events.event_bus import get_event_bus  # type: ignore
except Exception:  # pragma: no cover
    get_event_bus = None  # type: ignore

logger = logging.getLogger(__name__)

# Allow rapid restart in tests (port reuse after shutdown) to ensure updated
# adaptive severity configuration (e.g., trend window) is reflected.
try:
    ThreadingHTTPServer.allow_reuse_address = True  # type: ignore[attr-defined]
except Exception:
    pass

from . import http_server_registry as _registry

# Backward compatibility: retain names but delegate to registry globals
def _get_server_thread():
    return _registry.SERVER_THREAD
def _set_server_thread(t):
    _registry.SERVER_THREAD = t
def _get_http_server():
    return _registry.HTTP_SERVER
def _set_http_server(s):
    _registry.HTTP_SERVER = s

_SERVER_THREAD: Optional[threading.Thread] = None  # legacy alias (unused after refactor)
_HTTP_SERVER: Optional[ThreadingHTTPServer] = None  # legacy alias (unused after refactor)
_LAST_WINDOW: Optional[int] = None
_GENERATION: int = 0  # increments on each forced reload for debug/verification
_SNAPSHOT_CACHE_ENV_INITIAL: str | None = None

class _CatalogHandler(BaseHTTPRequestHandler):
    server_version = "G6CatalogHTTP/1.0"

    # Swallow benign network termination errors that can surface as uncaught exceptions
    # in daemon threads during test teardown (causing non-zero pytest exit despite all
    # tests passing). These occur when clients close connections mid-write (BrokenPipe,
    # ConnectionResetError) or during interpreter shutdown (ValueError on I/O ops).
    _BENIGN_ERRORS = (BrokenPipeError, ConnectionResetError, TimeoutError)

    def handle(self):  # type: ignore[override]
        try:
            super().handle()
        except self._BENIGN_ERRORS as e:  # pragma: no cover - timing dependent
            try:
                logger.debug("catalog_http: benign socket error suppressed: %s", e)
            except Exception:
                pass
        except Exception as e:  # pragma: no cover
            # Fallback: suppress noisy teardown exceptions but keep debug trace
            logger.debug("catalog_http: unexpected handler error suppressed: %r", e, exc_info=True)

    @staticmethod
    def _check_basic_auth(headers) -> bool:
        """Return True if authorized or auth not configured; False if challenge required.

        This helper centralizes Basic Auth logic for easier testing and reduces duplication.
        """
        user = os.environ.get('G6_HTTP_BASIC_USER')
        pw = os.environ.get('G6_HTTP_BASIC_PASS')
        if not user or not pw:
            return True  # auth not enabled
        expected = base64.b64encode(f"{user}:{pw}".encode()).decode()
        auth_header = headers.get('Authorization') if headers else None
        if not auth_header or not auth_header.startswith('Basic '):
            return False
        supplied = auth_header.split(' ', 1)[1]
        return supplied == expected

    def _set_headers(self, code: int = 200, ctype: str = 'application/json') -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()

    def log_message(self, format, *args):  # silence default noisy logging
        logger.debug("catalog_http: %s", format % args)

    def do_GET(self):  # noqa: N802
        # Helper inside handler to build adaptive theme payload (shared REST + SSE)
        def _build_adaptive_payload():  # local to avoid top-level import cost if unused
            try:
                from src.adaptive import severity as _severity  # type: ignore
            except Exception:
                return {
                    'palette': {
                        'info': os.environ.get('G6_ADAPTIVE_ALERT_COLOR_INFO') or '#6BAF92',
                        'warn': os.environ.get('G6_ADAPTIVE_ALERT_COLOR_WARN') or '#FFC107',
                        'critical': os.environ.get('G6_ADAPTIVE_ALERT_COLOR_CRITICAL') or '#E53935',
                    },
                    'active_counts': {},
                    'trend': {},
                    'smoothing_env': {}
                }
            palette = {
                'info': os.environ.get('G6_ADAPTIVE_ALERT_COLOR_INFO') or '#6BAF92',
                'warn': os.environ.get('G6_ADAPTIVE_ALERT_COLOR_WARN') or '#FFC107',
                'critical': os.environ.get('G6_ADAPTIVE_ALERT_COLOR_CRITICAL') or '#E53935',
            }
            enabled = getattr(_severity, 'enabled', lambda: False)()
            payload = {
                'palette': palette,
                'active_counts': _severity.get_active_severity_counts() if enabled else {},
                'trend': _severity.get_trend_stats() if enabled else {},
                'smoothing_env': {
                    'trend_window': os.environ.get('G6_ADAPTIVE_SEVERITY_TREND_WINDOW'),
                    'smooth': os.environ.get('G6_ADAPTIVE_SEVERITY_TREND_SMOOTH'),
                    'critical_ratio': os.environ.get('G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO'),
                    'warn_ratio': os.environ.get('G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO'),
                }
            }
            # Include enriched per-type state summary at top-level (latest snapshot already inside trend)
            try:
                payload['per_type'] = _severity.get_active_severity_state() if enabled else {}
            except Exception:
                payload['per_type'] = {}
            return payload
        if self.path.startswith('/health'):
            # Include 'status' for legacy test expectations while retaining 'ok' field
            self._set_headers(200)
            self.wfile.write(b'{"ok":true,"status":"ok"}')
            return
        # Basic Auth (except /health)
        if not self._check_basic_auth(self.headers):
            self.send_response(401)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('WWW-Authenticate', 'Basic realm="G6", charset="UTF-8"')
            self.end_headers()
            self.wfile.write(b'Unauthorized')
            return
        if self.path.startswith('/events'):
            # /events/stats JSON introspection (non-stream) handled first
            if self.path.startswith('/events/stats'):
                if get_event_bus is None:
                    self._set_headers(503)
                    self.wfile.write(b'{"error":"event_bus_unavailable"}')
                    return
                try:
                    bus = get_event_bus()
                    snap = bus.stats_snapshot()
                    # Future Phase additions: forced_full counts, backlog utilization precomputed, connection durations summary
                    body = json.dumps(snap, separators=(',',':')).encode('utf-8')
                    self._set_headers(200)
                    self.wfile.write(body)
                except Exception:
                    logger.exception("catalog_http: failure building events stats")
                    self._set_headers(500)
                    self.wfile.write(b'{"error":"events_stats_failed"}')
                return
            if get_event_bus is None:
                self._set_headers(503)
                self.wfile.write(b'{"error":"event_bus_unavailable"}')
                return
            try:
                from urllib.parse import urlparse, parse_qs
                bus = get_event_bus()
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query or '')
                force_full = False
                try:
                    vals = qs.get('force_full') or qs.get('forcefull') or []
                    if vals:
                        raw = vals[0]
                        if raw is None or str(raw).strip() == '' or str(raw).lower() in ('1','true','yes','on'):
                            force_full = True
                except Exception:
                    force_full = False
                type_filters = []
                for key in ('type', 'types'):
                    for item in qs.get(key, []):
                        for part in item.split(','):
                            part = part.strip()
                            if part:
                                type_filters.append(part)
                type_filters = list(dict.fromkeys(type_filters))  # dedupe preserve order
                last_event_id = 0
                hdr_id = (self.headers.get('Last-Event-ID') if self.headers else None) or None
                if hdr_id:
                    try:
                        last_event_id = int(hdr_id)
                    except Exception:
                        last_event_id = 0
                if 'last_id' in qs:
                    try:
                        last_event_id = int(qs['last_id'][0])
                    except Exception:
                        pass
                backlog_limit = None
                if 'backlog' in qs:
                    try:
                        backlog_limit = max(0, int(qs['backlog'][0]))
                    except Exception:
                        backlog_limit = None
                retry_ms = int(os.environ.get('G6_EVENTS_SSE_RETRY_MS', '5000'))
                poll_interval = float(os.environ.get('G6_EVENTS_SSE_POLL', '0.5'))
                heartbeat_interval = float(os.environ.get('G6_EVENTS_SSE_HEARTBEAT', '5.0'))
                last_heartbeat = time.time()
                conn_start_ts = time.time()
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'keep-alive')
                self.end_headers()
                self.wfile.write(f"retry: {retry_ms}\n".encode('utf-8'))
                self.wfile.flush()
                # Consumer bookkeeping start
                try:
                    if hasattr(bus, '_consumer_started'):
                        bus._consumer_started()  # type: ignore[attr-defined]
                except Exception:
                    pass

                def _send(event) -> None:
                    nonlocal last_event_id, last_heartbeat
                    payload = event.as_sse_payload()
                    # Client-side latency observation hook (in-process consumer path)
                    try:
                        from src.events.latency_client import observe_event_latency  # type: ignore
                        observe_event_latency(payload)
                    except Exception:
                        pass
                    evt_type = payload.get('type')
                    if type_filters and evt_type not in type_filters:
                        return
                    try:
                        # Flush latency measurement (publish->flush) best-effort
                        if is_truthy_env('G6_SSE_FLUSH_LATENCY_CAPTURE'):
                            try:
                                pub_ts = None
                                if isinstance(payload, dict):
                                    inner = payload.get('payload')  # nested structure
                                    if isinstance(inner, dict):
                                        pub_ts = inner.get('publish_unixtime')
                                if isinstance(pub_ts, (int,float)):
                                    now_ts = time.time()
                                    flush_latency = max(0.0, now_ts - pub_ts)
                                    from src.metrics import get_metrics  # type: ignore
                                    m = get_metrics()
                                    if m and hasattr(m, 'sse_flush_seconds'):
                                        try:
                                            hist = getattr(m, 'sse_flush_seconds')
                                            observe = getattr(hist, 'observe', None)
                                            if callable(observe):
                                                observe(flush_latency)
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                        # Trace context: flush stage
                        if is_truthy_env('G6_SSE_TRACE') and isinstance(payload, dict):
                            try:
                                inner = payload.get('payload')
                                if isinstance(inner, dict):
                                    tr = inner.get('_trace')
                                    if isinstance(tr, dict) and 'flush_ts' not in tr:
                                        tr['flush_ts'] = time.time()
                                        # Metric stage counter
                                        try:
                                            from src.metrics import get_metrics  # type: ignore
                                            m = get_metrics()
                                            if m and hasattr(m, 'sse_trace_stages_total'):
                                                ctr = getattr(m, 'sse_trace_stages_total')
                                                inc = getattr(ctr, 'inc', None)
                                                if callable(inc):
                                                    inc()
                                        except Exception:
                                            pass
                            except Exception:
                                pass
                        self.wfile.write(f"id: {event.event_id}\n".encode('utf-8'))
                        if evt_type:
                            self.wfile.write(f"event: {evt_type}\n".encode('utf-8'))
                        data = json.dumps(payload, separators=(',', ':'))
                        self.wfile.write(f"data: {data}\n\n".encode('utf-8'))
                        self.wfile.flush()
                        last_event_id = event.event_id
                        last_heartbeat = time.time()
                    except Exception:
                        raise

                # Initial backlog replay
                try:
                    # Optional forced injection of current full snapshot baseline
                    if force_full:
                        try:
                            latest_full = getattr(bus, 'latest_full_snapshot', None)
                            if callable(latest_full):
                                snap = latest_full()
                                if isinstance(snap, dict):
                                    # fabricate synthetic event object wrapper
                                    class _Synthetic:
                                        def __init__(self, eid: int, payload: dict, gen: int):
                                            self.event_id = eid
                                            self._payload = payload
                                            self.event_type = 'panel_full'
                                            self._gen = gen
                                        def as_sse_payload(self):
                                            p = dict(self._payload)
                                            if '_generation' not in p:
                                                p['_generation'] = getattr(bus, '_generation', 0)  # type: ignore[attr-defined]
                                            return {
                                                'id': self.event_id,
                                                'sequence': self.event_id,
                                                'type': 'panel_full',
                                                'timestamp_ist': p.get('timestamp_ist') or '',
                                                'payload': p,
                                                'generation': p.get('_generation'),
                                                # Provide synthetic publish_unixtime for latency metrics parity
                                                'publish_unixtime': time.time()
                                            }
                                    synthetic = _Synthetic(last_event_id, snap, getattr(bus, '_generation', 0))
                                    _send(synthetic)
                        except Exception:
                            logger.debug("catalog_http: force_full injection failed", exc_info=True)
                    for ev in bus.get_since(last_event_id, limit=backlog_limit):
                        _send(ev)
                except Exception:
                    return

                # Streaming loop
                try:
                    while True:
                        try:
                            pending = bus.get_since(last_event_id)
                            if pending:
                                for ev in pending:
                                    _send(ev)
                            else:
                                now = time.time()
                                if now - last_heartbeat >= heartbeat_interval:
                                    try:
                                        self.wfile.write(b': keep-alive\n\n')
                                        self.wfile.flush()
                                    except Exception:
                                        break
                                    last_heartbeat = now
                                time.sleep(poll_interval)
                        except Exception:
                            break
                finally:
                    # Consumer bookkeeping stop (only for streaming path, not stats)
                    try:
                        if get_event_bus is not None:
                            bus = get_event_bus()
                            duration = max(0.0, time.time() - conn_start_ts)
                            if hasattr(bus, '_observe_connection_duration'):
                                try:
                                    bus._observe_connection_duration(duration)  # type: ignore[attr-defined]
                                except Exception:
                                    pass
                            if hasattr(bus, '_consumer_stopped'):
                                bus._consumer_stopped()  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                logger.exception("catalog_http: failure serving SSE events")
            return
        if self.path.startswith('/catalog'):
            try:
                # Dynamically resolve build_catalog each request to avoid stale binding if server thread not reloaded
                try:
                    from . import catalog as _cat_mod  # type: ignore
                    build_fn = getattr(_cat_mod, 'build_catalog', build_catalog)
                except Exception:  # pragma: no cover
                    build_fn = build_catalog
                runtime_status = os.environ.get('G6_RUNTIME_STATUS_FILE', 'data/runtime_status.json')
                # Always build anew (cheap for tests) to avoid stale file logic complexity
                catalog = build_fn(runtime_status_path=runtime_status)
                # Overwrite any integrity with a freshly recomputed inline version (idempotent)
                try:
                    events_path = os.environ.get('G6_EVENTS_LOG_PATH', os.path.join('logs','events.log'))
                    cycles=[]
                    try:
                        with open(events_path,'r',encoding='utf-8') as fh:
                            for i,line in enumerate(fh):
                                if i>=200_000: break
                                if 'cycle_start' not in line: continue
                                try:
                                    obj=json.loads(line)
                                except Exception:
                                    continue
                                if obj.get('event')=='cycle_start':
                                    c=(obj.get('context') or {}).get('cycle')
                                    if isinstance(c,int): cycles.append(c)
                    except FileNotFoundError:
                        cycles=[]
                    missing=0
                    if cycles:
                        cs=sorted(set(cycles))
                        for a,b in zip(cs, cs[1:]):
                            if b>a+1: missing += (b-a-1)
                    catalog['integrity']={
                        'cycles_observed': len(cycles),
                        'first_cycle': min(cycles) if cycles else None,
                        'last_cycle': max(cycles) if cycles else None,
                        'missing_count': missing,
                        'status': 'OK' if missing==0 else 'GAPS',
                        'source': 'http_inline'
                    }
                except Exception:
                    logger.debug('catalog_http: inline_integrity_override_failed', exc_info=True)
                # Minimal final fallback if somehow integrity is still absent
                if 'integrity' not in catalog:
                    try:
                        events_path = os.environ.get('G6_EVENTS_LOG_PATH', os.path.join('logs','events.log'))
                        cycles=[]
                        try:
                            with open(events_path,'r',encoding='utf-8') as fh:
                                for i,line in enumerate(fh):
                                    if i>=100_000: break
                                    if 'cycle_start' not in line: continue
                                    try:
                                        obj=json.loads(line)
                                    except Exception:
                                        continue
                                    if obj.get('event')=='cycle_start':
                                        c=(obj.get('context') or {}).get('cycle')
                                        if isinstance(c,int): cycles.append(c)
                        except FileNotFoundError:
                            cycles=[]
                        missing=0
                        if cycles:
                            cs=sorted(set(cycles))
                            for a,b in zip(cs, cs[1:]):
                                if b>a+1: missing += (b-a-1)
                        catalog['integrity']={
                            'cycles_observed': len(cycles),
                            'first_cycle': min(cycles) if cycles else None,
                            'last_cycle': max(cycles) if cycles else None,
                            'missing_count': missing,
                            'status': 'OK' if missing==0 else 'GAPS',
                            'source': 'fallback_final'
                        }
                    except Exception:
                        logger.debug('catalog_http: integrity_fallback_final_failed', exc_info=True)
                body = json.dumps(catalog).encode('utf-8')
                self._set_headers(200)
                self.wfile.write(body)
            except Exception:
                logger.exception("catalog_http: failure building catalog")
                self._set_headers(500)
                self.wfile.write(b'{"error":"catalog_build_failed"}')
            return
        if self.path.startswith('/snapshots'):
            # Transitional logic:
            #  - If HTTP globally disabled via G6_CATALOG_HTTP_DISABLE -> 410 Gone (feature de-scoped)
            #  - Else if cache not explicitly enabled via env -> 400 (tests expect strict explicit enable)
            if is_truthy_env('G6_CATALOG_HTTP_DISABLE'):
                self._set_headers(410)
                self.wfile.write(b'{"error":"snapshots_endpoint_disabled"}')
                return
            # Explicit enable signals only (no implicit auto-enable from existing cache contents)
            env_enabled = is_truthy_env('G6_SNAPSHOT_CACHE')
            force_enabled = is_truthy_env('G6_SNAPSHOT_CACHE_FORCE')
            if not (env_enabled or force_enabled):
                self._set_headers(400)
                self.wfile.write(b'{"error":"snapshot_cache_disabled"}')
                return
            # Serve snapshot cache
            try:
                from src.domain import snapshots_cache as _snap  # type: ignore
                from urllib.parse import urlparse, parse_qs
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query or '')
                index_filter = None
                if 'index' in qs:
                    vals = qs.get('index') or []
                    if vals:
                        index_filter = vals[0]
                snap_dict = _snap.serialize()
                if index_filter:
                    try:
                        snap_list = snap_dict.get('snapshots') or []
                        if not isinstance(snap_list, list):  # safety guard (corrupted cache)
                            snap_list = []
                        filtered = [s for s in snap_list if isinstance(s, dict) and s.get('index') == index_filter]
                        snap_dict['snapshots'] = filtered
                        snap_dict['count'] = len(filtered)
                    except Exception:
                        pass
                try:
                    logger.debug('catalog_http: snapshots serve count=%s keys=%s', snap_dict.get('count'), list(snap_dict.keys()))
                except Exception:
                    pass
                body = json.dumps(snap_dict).encode('utf-8')
                self._set_headers(200)
                self.wfile.write(body)
            except Exception:
                logger.exception('catalog_http: snapshots_serve_failed')
                self._set_headers(500)
                self.wfile.write(b'{"error":"snapshots_serve_failed"}')
            return
        if self.path.startswith('/adaptive/theme'):
            # Distinguish /adaptive/theme/stream for SSE
            if self.path.startswith('/adaptive/theme/stream'):
                # Minimal SSE implementation: send event every few seconds until client disconnects.
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Cache-Control', 'no-cache')
                    self.send_header('Connection', 'keep-alive')
                    self.end_headers()
                    interval = float(os.environ.get('G6_ADAPTIVE_THEME_STREAM_INTERVAL','3'))
                    # Soft limit runtime to prevent runaway threads; client can reconnect.
                    max_events = int(os.environ.get('G6_ADAPTIVE_THEME_STREAM_MAX_EVENTS','200'))
                    diff_only = is_truthy_env('G6_ADAPTIVE_THEME_SSE_DIFF')
                    last_payload = None
                    for i in range(max_events):
                        full_payload = _build_adaptive_payload()
                        send_obj = full_payload
                        if diff_only and last_payload is not None:
                            # Build shallow diff of changed top-level keys (active_counts, per_type, trend ratios)
                            from typing import Any as _Any
                            diff: dict[str, _Any] = {'diff': True}
                            try:
                                # Compare active_counts
                                if full_payload.get('active_counts') != last_payload.get('active_counts'):
                                    diff['active_counts'] = full_payload.get('active_counts')
                                # Compare per_type active levels & resolved counts
                                cur_pt = full_payload.get('per_type') or {}
                                prev_pt = last_payload.get('per_type') or {}
                                changed_pt = {}
                                for k,v in cur_pt.items():
                                    pv = prev_pt.get(k)
                                    if not isinstance(pv, dict) or pv.get('active') != v.get('active') or pv.get('resolved_count') != v.get('resolved_count') or pv.get('last_change_cycle') != v.get('last_change_cycle'):
                                        changed_pt[k] = v
                                if changed_pt:
                                    diff['per_type'] = changed_pt
                                # Trend: send only ratios + latest snapshot counts if changed
                                cur_trend = (full_payload.get('trend') or {})
                                prev_trend = (last_payload.get('trend') or {})
                                send_trend = {}
                                for fld in ('critical_ratio','warn_ratio'):
                                    if cur_trend.get(fld) != prev_trend.get(fld):
                                        send_trend[fld] = cur_trend.get(fld)
                                # Latest snapshot counts compare
                                try:
                                    cur_snaps = cur_trend.get('snapshots') or []
                                    prev_snaps = prev_trend.get('snapshots') or []
                                    if cur_snaps and prev_snaps:
                                        cur_last = cur_snaps[-1]
                                        prev_last = prev_snaps[-1]
                                        if cur_last.get('counts') != prev_last.get('counts'):
                                            send_trend['latest'] = cur_last.get('counts')
                                except Exception:
                                    pass
                                if send_trend:
                                    diff['trend'] = send_trend
                                if len(diff) > 1:
                                    send_obj = diff
                            except Exception:
                                send_obj = full_payload
                        data = json.dumps(send_obj)
                        try:
                            self.wfile.write(f"data: {data}\n\n".encode('utf-8'))
                            self.wfile.flush()
                        except Exception:
                            break
                        last_payload = full_payload
                        time.sleep(interval)
                except Exception:
                    logger.exception("catalog_http: SSE adaptive theme failure")
                return
            try:
                payload = _build_adaptive_payload()
                body_raw = json.dumps(payload, separators=(',',':')).encode('utf-8')
                # ETag (sha256 hex of payload)
                etag = hashlib.sha256(body_raw).hexdigest()[:16]
                inm = self.headers.get('If-None-Match') if self.headers else None
                if inm == etag:
                    self.send_response(304)
                    self.send_header('ETag', etag)
                    self.end_headers()
                    return
                use_gzip = is_truthy_env('G6_ADAPTIVE_THEME_GZIP') and 'gzip' in (self.headers.get('Accept-Encoding') or '')
                if use_gzip:
                    buf = io.BytesIO()
                    with gzip.GzipFile(fileobj=buf, mode='wb') as gz:
                        gz.write(body_raw)
                    body = buf.getvalue()
                    self.send_response(200)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Content-Encoding','gzip')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('ETag', etag)
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(200)
                    self.send_header('Content-Type','application/json')
                    self.send_header('Cache-Control','no-store')
                    self.send_header('ETag', etag)
                    self.send_header('Content-Length', str(len(body_raw)))
                    self.end_headers()
                    self.wfile.write(body_raw)
            except Exception:
                logger.exception("catalog_http: failure serving adaptive theme")
                self._set_headers(500)
                self.wfile.write(b'{"error":"adaptive_theme_failed"}')
            return
        self._set_headers(404)
        self.wfile.write(b'{"error":"not_found"}')


def shutdown_http_server(timeout: float = 2.0) -> None:
    """Explicitly shutdown existing HTTP server if running.

    Safe to call even if no server running. Ensures port freed for deterministic tests.
    """
    server = _get_http_server()
    th = _get_server_thread()
    if server:
        try:
            server.shutdown()
        except Exception:
            pass
        # Ensure underlying socket fully released (prevents ResourceWarning)
        try:
            server.server_close()
        except Exception:
            pass
    if th:
        try:
            th.join(timeout=timeout)
        except Exception:
            pass
    _set_http_server(None)
    _set_server_thread(None)

def start_http_server_in_thread() -> None:
    """Start (or reload) catalog HTTP server in background thread.

    Set G6_CATALOG_HTTP_FORCE_RELOAD=1 to force a shutdown + restart (used in tests
    when code updated mid-session). Safe to call multiple times.
    """
    # Use registry-backed getters/setters to avoid module reload desync
    if is_truthy_env('G6_CATALOG_HTTP_DISABLE'):
        # If disable flag set, ensure any existing server is shut down and return
        try:
            shutdown_http_server()
        except Exception:
            pass
        logger.info("catalog_http: disabled via G6_CATALOG_HTTP_DISABLE")
        return
    force_reload = is_truthy_env('G6_CATALOG_HTTP_FORCE_RELOAD')
    rebuild_flag = is_truthy_env('G6_CATALOG_HTTP_REBUILD')
    if rebuild_flag:
        force_reload = True
    # Always perform a shutdown first if rebuild requested (even if no thread)
    if rebuild_flag:
        try:
            shutdown_http_server()
        except Exception:
            pass
    # Auto reload if adaptive trend window changed (test isolation convenience)
    try:
        from src.adaptive import severity as _severity  # type: ignore
        current_window = getattr(_severity, '_trend_window')()
    except Exception:
        current_window = None  # type: ignore
    global _LAST_WINDOW
    if _LAST_WINDOW is not None and current_window is not None and current_window != _LAST_WINDOW:
        force_reload = True
    if current_window is not None:
        _LAST_WINDOW = current_window
    th_existing = _get_server_thread()
    if th_existing and th_existing.is_alive():
        if not force_reload:
            # Host/port drift triggers reload
            try:
                srv = _get_http_server()
                if srv:
                    srv_host, srv_port = srv.server_address[:2]
                    req_host = os.environ.get('G6_CATALOG_HTTP_HOST', '127.0.0.1')
                    try:
                        req_port = int(os.environ.get('G6_CATALOG_HTTP_PORT','9315'))
                    except ValueError:
                        req_port = 9315
                    if srv_host != req_host or srv_port != req_port:
                        force_reload = True
            except Exception:
                pass
        if not force_reload:
            return
        # Perform reload (already shut down earlier if rebuild_flag; but ensure)
        try:
            shutdown_http_server()
        except Exception:
            pass
        try:
            time.sleep(0.05)
        except Exception:
            pass
    host = os.environ.get('G6_CATALOG_HTTP_HOST', '127.0.0.1')
    try:
        port = int(os.environ.get('G6_CATALOG_HTTP_PORT', '9315'))
    except ValueError:
        port = 9315
    def _run():
        try:
            # Ensure latest catalog logic (hot-reload friendly during tests / dev)
            try:
                import importlib
                from . import catalog as _cat_mod  # type: ignore
                _cat_mod = importlib.reload(_cat_mod)  # type: ignore
                globals()['build_catalog'] = _cat_mod.build_catalog  # update binding
                globals()['CATALOG_PATH'] = _cat_mod.CATALOG_PATH
            except Exception:
                logger.debug('catalog_http: catalog_reload_failed', exc_info=True)
            # Capture initial snapshot cache env state for runtime transition detection
            global _SNAPSHOT_CACHE_ENV_INITIAL
            _SNAPSHOT_CACHE_ENV_INITIAL = os.environ.get('G6_SNAPSHOT_CACHE')
            httpd = ThreadingHTTPServer((host, port), _CatalogHandler)
            _set_http_server(httpd)
        except Exception:
            logger.exception("catalog_http: failed to bind %s:%s", host, port)
            return
        # Increment generation marker for debug; attach to server for introspection
        global _GENERATION
        _GENERATION += 1
        try:
            setattr(httpd, '_g6_generation', _GENERATION)
        except Exception:
            pass
        logger.info("catalog_http: serving on %s:%s (gen=%s rebuild=%s force_reload=%s)", host, port, _GENERATION, rebuild_flag, force_reload)
        try:
            httpd.serve_forever(poll_interval=0.5)
        except Exception:
            logger.exception("catalog_http: server crashed")
        finally:
            # Ensure socket fully released (mitigate ResourceWarning)
            try:
                httpd.server_close()
            except Exception:
                pass
    t = threading.Thread(target=_run, name="g6-catalog-http", daemon=True)
    t.start()
    _set_server_thread(t)

__all__ = ["start_http_server_in_thread", "shutdown_http_server"]
