"""Shared SSE / unified HTTP helper utilities.

This module centralizes the overlapping security & connection governance logic
between the legacy `sse_http` implementation and the cleaner `unified_http`
server. Initial extraction focuses on:
  * Security config resolution (token, IP allow list, UA allow list, CORS origin)
  * Per‑IP connection attempt window parsing & rate specification parsing
  * User-Agent allow list enforcement (precedence over rate limiting)
  * Per-IP connection rate limiting with second‑chance pruning heuristic

Design goals:
  * Zero behavior drift vs existing inline logic (tests asserting ordering of
    401/403/429 responses must continue to pass)
  * No new hard dependency on `sse_http` to avoid circular imports. Callers pass
    `ip_conn_window` (mutable dict) and optionally a `handlers_ref` iterable used
    for stale timestamp pruning.
  * Metrics objects (Prometheus counters) are passed in via a light
    dictionary interface so callers decide what gets incremented. Absent
    / None metrics are ignored silently.

Phase 2 extends extraction to include:
    * Event framing / write helper (mirrors SSEHandler._write_event semantics)
    * Per-connection event rate limiting (token bucket) used by both handlers
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SecurityConfig:
    token_required: str | None
    allow_ips: set[str]
    rate_spec: str
    ua_allow: str  # raw comma list (kept string for parity)
    allow_origin: str | None


def load_security_config() -> SecurityConfig:
    """Resolve security config using env_config (preferred) with legacy fallbacks.

    Mirrors logic in existing handlers; ordering preserved.
    """
    _direct_override = os.getenv('G6_SSE_SECURITY_DIRECT') not in (None, '0', 'false', 'no', 'off')
    if not _direct_override:
        try:  # Preferred aggregated env loader
            from scripts.summary.env_config import load_summary_env  # type: ignore
            _env = load_summary_env()
            token_required = _env.sse_token
            allow_ips = set(_env.sse_allow_ips)
            rate_spec = _env.sse_connect_rate_spec or ''
            ua_allow_raw = _env.sse_allow_user_agents or []
            allow_origin_cfg = _env.sse_allow_origin
            ua_allow = ','.join([p for p in ua_allow_raw if p])
        except Exception:
            token_required = os.getenv('G6_SSE_API_TOKEN')
            allow_ips = {ip.strip() for ip in (os.getenv('G6_SSE_IP_ALLOW') or '').split(',') if ip.strip()}
            rate_spec = os.getenv('G6_SSE_IP_CONNECT_RATE', '')
            ua_allow = os.getenv('G6_SSE_UA_ALLOW', '')
            allow_origin_cfg = os.getenv('G6_SSE_ALLOW_ORIGIN')
    else:  # direct legacy path
        token_required = os.getenv('G6_SSE_API_TOKEN')
        allow_ips = {ip.strip() for ip in (os.getenv('G6_SSE_IP_ALLOW') or '').split(',') if ip.strip()}
        rate_spec = os.getenv('G6_SSE_IP_CONNECT_RATE', '')
        ua_allow = os.getenv('G6_SSE_UA_ALLOW', '')
        allow_origin_cfg = os.getenv('G6_SSE_ALLOW_ORIGIN')
    return SecurityConfig(token_required, allow_ips, rate_spec, ua_allow, allow_origin_cfg)


def parse_rate_spec(rate_spec: str) -> tuple[int, int]:
    """Parse rate spec of form 'X:Y' or 'X/Y' (max_conn_ip : window_seconds).
    Falls back gracefully on malformed inputs (returns (0, 60) meaning disabled).
    """
    parts = [p for p in rate_spec.replace(':', '/').split('/') if p]
    try:
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
        if len(parts) == 1:
            return int(parts[0]), 60
    except Exception:
        pass
    return 0, 60


def _inc(metric_obj: Any) -> None:
    if metric_obj is None:
        return
    try:
        metric_obj.inc()  # type: ignore[attr-defined]
    except Exception:
        pass


def enforce_auth_and_rate(
    handler: Any,
    cfg: SecurityConfig,
    *,
    ip_conn_window: dict[str, list],
    handlers_ref: Iterable[Any] | None = None,
    metrics: dict[str, Any] | None = None,
    debug_env: str = 'G6_SSE_DEBUG',
) -> int | None:
    """Apply auth (token), IP allow list, UA allow list, and per-IP rate limiting.

    Returns HTTP status code on rejection (already written to client) else None.
    Ordering must remain: 401 -> 403 (IP / UA) -> 429.
    Metrics keys honored (if present in metrics dict):
      'auth_fail', 'forbidden_ip', 'forbidden_ua', 'rate_limited_conn'
    """
    metrics = metrics or {}

    # Token auth
    if cfg.token_required:
        provided = handler.headers.get('X-API-Token') if getattr(handler, 'headers', None) else None
        if provided != cfg.token_required:
            _inc(metrics.get('auth_fail'))
            _plain(handler, 401, 'unauthorized')
            return 401

    client_ip = (
        handler.client_address[0]
        if isinstance(getattr(handler, 'client_address', None), tuple)
        else (
            getattr(handler, 'client_address', ('',))[0]
            if getattr(handler, 'client_address', None)
            else ''
        )
    )

    # IP allow list
    if cfg.allow_ips and client_ip not in cfg.allow_ips:
        _inc(metrics.get('forbidden_ip'))
        _plain(handler, 403, 'forbidden')
        return 403

    # UA allow list (precedence over rate limiting)
    ua_allow = cfg.ua_allow
    ua = handler.headers.get('User-Agent', '') if getattr(handler, 'headers', None) else ''
    ua_hash = hashlib.sha256(ua.encode('utf-8')).hexdigest() if ua else ''
    if ua_allow:
        allow_parts = [p.strip() for p in ua_allow.split(',') if p.strip()]
        if allow_parts and not any(part in ua for part in allow_parts):
            _inc(metrics.get('forbidden_ua'))
            logger.warning("sse_conn reject ip=%s reason=forbidden_ua ua_hash=%s", client_ip, ua_hash[:12])
            _plain(handler, 403, 'forbidden')
            return 403

    # Rate limiting
    max_conn_ip, win_sec = parse_rate_spec(cfg.rate_spec)
    if max_conn_ip > 0 and client_ip:
        now = time.time()
        window = ip_conn_window.setdefault(client_ip, [])
        cutoff = now - win_sec
        while window and window[0] < cutoff:
            window.pop(0)
        if len(window) > max_conn_ip:
            del window[:-max_conn_ip]
        _debug_active = (
            os.getenv(debug_env, '') not in ('', '0', 'false', 'no', 'off')
            or os.getenv('PYTEST_CURRENT_TEST')
        )
        if len(window) >= max_conn_ip:
            # Second‑chance pruning based on active handlers
            try:  # noqa: PERF203 - per-item isolation to avoid aborting loop on one bad handler
                if handlers_ref is not None:
                    active_for_ip = 0
                    for _h in list(handlers_ref):
                        try:
                            if getattr(_h, 'client_address', None) and _h.client_address[0] == client_ip:
                                active_for_ip += 1
                        except Exception:  # noqa: PERF203 - robustness over micro-optimization
                            # Defensive: single bad handler shouldn't break pruning evaluation
                            pass
                    if active_for_ip < max_conn_ip:
                        target = max(0, max_conn_ip - 1)
                        if len(window) > target:
                            del window[: len(window) - target]
            except Exception:
                pass
        if len(window) >= max_conn_ip:
            if _debug_active:
                try:
                    print(
                        f"[sse-debug][shared] rate_limit_block ip={client_ip} "
                        f"attempts={len(window)} max={max_conn_ip} "
                        f"window={window} now={now:.6f}"
                    )
                except Exception:
                    pass
            _inc(metrics.get('rate_limited_conn'))
            _plain(handler, 429, 'rate limited', headers={'Retry-After': '5'})
            return 429
        window.append(now)
        if _debug_active:
            try:
                print(
                    f"[sse-debug][shared] rate_limit_allow ip={client_ip} "
                    f"size={len(window)}/{max_conn_ip} window={window} "
                    f"now={now:.6f}"
                )
            except Exception:
                pass
    return None


def _plain(handler: Any, code: int, body: str, *, headers: dict[str, str] | None = None) -> None:
    try:
        handler.send_response(code)
        handler.send_header('Content-Type', 'text/plain')
        if headers:
            for k, v in headers.items():
                handler.send_header(k, v)
        handler.end_headers()
        writer = getattr(getattr(handler, 'wfile', None), 'write', None)
        if callable(writer):
            try:
                writer(body.encode('utf-8'))
            except Exception:
                pass
    except Exception:
        pass

def write_sse_event(
    handler: Any,
    evt: dict[str, Any],
    *,
    max_bytes_env: str = 'G6_SSE_MAX_EVENT_BYTES',
    security_metric: Any | None = None,
    events_sent_metric: Any | None = None,
    h_event_size: Any | None = None,
    h_event_latency: Any | None = None,
    debug_log_path: str = 'data/panels/_sse_debug_events.log',
) -> None:
    """Frame and write a single SSE event with metrics & truncation parity.

    Mirrors logic in sse_http.SSEHandler._write_event; metrics are optional
    objects implementing inc()/observe().
    """
    try:
        etype_raw = (evt.get('event') if isinstance(evt, dict) else 'message') or 'message'
        etype = ''.join(ch for ch in etype_raw if ch.isalnum() or ch in ('_', '-'))[:40] or 'message'
        data = evt.get('data') if isinstance(evt, dict) else None
        try:
            max_bytes = int(os.getenv(max_bytes_env, '65536') or 65536)
        except Exception:
            max_bytes = 65536
        try:
            payload = json.dumps(data, separators=(',', ':')) if data is not None else ''
        except Exception:
            payload = '{}'
        if len(payload.encode('utf-8')) > max_bytes:
            if security_metric is not None:
                _inc(security_metric)
            payload = '{}'
            etype = 'truncated'
        out = f"event: {etype}\n" + (f"data: {payload}\n" if payload else '') + "\n"
        encoded = out.encode('utf-8')
        try:
            handler.wfile.write(encoded)  # type: ignore[attr-defined]
            handler.wfile.flush()  # type: ignore[attr-defined]
        except Exception:
            return
        if events_sent_metric is not None:
            _inc(events_sent_metric)
        # advanced metrics
        try:
            if h_event_size is not None:
                h_event_size.observe(len(encoded))  # type: ignore[attr-defined]
            if h_event_latency is not None and isinstance(evt, dict):
                ts_emit = evt.get('_ts_emit')
                if isinstance(ts_emit, (int, float)):
                    h_event_latency.observe(max(0.0, time.time() - ts_emit))  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            with open(debug_log_path, 'a', encoding='utf-8') as _df:
                _df.write(f"wrote:{etype}\n")
        except Exception:
            pass
    except Exception:
        pass


def allow_event_token_bucket(
    handler: Any,
    *,
    limit_env: str = 'G6_SSE_EVENTS_PER_SEC',
    burst_factor: int = 2,
) -> bool:
    """Token-bucket limiter (per connection) matching SSEHandler._allow_event.

    Returns True if event may be sent, False if it should be dropped.
    State stored on handler as _rl = [tokens, last_ts].
    """
    try:
        limit = int(os.getenv(limit_env, '100') or 100)
    except Exception:
        limit = 100
    if limit <= 0:
        return True
    now = time.time()
    state = getattr(handler, '_rl', None)
    if state is None:
        state = [limit * burst_factor, now]
        try:
            handler._rl = state
        except Exception:
            pass
    tokens, last = state
    elapsed = now - last
    if elapsed > 0:
        tokens = min(limit * burst_factor, tokens + elapsed * limit)
    if tokens < 1:
        state[0] = tokens
        state[1] = now
        return False
    tokens -= 1
    state[0] = tokens
    state[1] = now
    return True


__all__ = [
    'SecurityConfig',
    'load_security_config',
    'parse_rate_spec',
    'enforce_auth_and_rate',
    'write_sse_event',
    'allow_event_token_bucket',
]
