"""Lightweight structured logging helpers for provider (Kite) events.

Goal: Provide a single, low‑risk instrumentation surface that can be
incrementally adopted in `kite_provider.py` without altering existing
behavior or legacy log messages. These helpers emit ONE JSON line per
provider operation (success or failure) with consistent keys so that
future ingestion / analytics pipelines have a stable contract.

Design Principles:
- Non-intrusive: if disabled (default), introduces near-zero overhead.
- Explicit gating: opt-in via env vars to avoid surprising log volume.
- Minimal surface: a context manager + one direct emit function.
- Resilient: never raise from logging path; fall back gracefully.
- JSON lines: machine-friendly; avoid locale/timezone ambiguity.

Enablement:
Set one of the following environment variables to a truthy value
("1", "true", "yes", case-insensitive) to enable emission:
  G6_STRUCT_LOG           (global structured logging gate)
  G6_PROVIDER_EVENTS      (narrow provider event gate)

If both are unset/false, helpers become no-ops.

Event Shape (base keys):
{
  "ts":            float (epoch seconds, high resolution),
  "event":         str   (namespace.domain.action.outcome),
  "namespace":     str   (e.g. "provider.kite"),
  "domain":        str   (e.g. "instruments"),
  "action":        str   (e.g. "fetch"),
  "outcome":       str   (success|error),
  "dur_ms":        int   (duration in milliseconds),
  "provider":      str   ("kite"),
  "thread":        str   (thread name),
  "pid":           int   (process id),
  "attempt":       int   (optional attempt counter when provided),
  "error_type":    str?  (present on failure),
  "error_msg":     str?  (truncated message on failure),
  "trace":         str?  (abridged traceback when enabled),
  ...additional caller supplied stable fields...
}

Contract Notes:
- Callers SHOULD prefer stable, lower-case snake_case keys.
- Avoid embedding large payloads (instrument lists, quotes arrays);
  instead expose counts (e.g. instruments_count=1234).
- Secrets MUST NOT be passed in additional fields. Helpers do not
  perform PII/secret scrubbing beyond simple length truncation.

Future Extensions (intentionally deferred):
- Sampling / rate limiting per event type.
- Emission to an alternate sink (queue / metrics) besides std logging.
- Automatic error taxonomy mapping once taxonomy classes land.

Usage Examples:

    from .provider_events import provider_event

    def get_instruments(...):
        with provider_event(domain="instruments", action="fetch") as evt:
            data = _client.instruments()
            evt.add_field("instruments_count", len(data))
            return data

    # Manual outcome override / extra fields:
    with provider_event("quotes", "ltp", symbol=sym) as evt:
        price = _client.ltp(sym)
        evt.add_field("cache_hit", cache_hit)
        return price

    # Direct emit (avoid context when duration not useful):
    emit_provider_event("health", "check", outcome="success", extra={"status": ok})

"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal

# Public, stable constants (importable by tests if desired)
PROVIDER_NAMESPACE = "provider.kite"
PROVIDER_NAME = "kite"
STRUCT_LOG_GATE_GLOBAL = "G6_STRUCT_LOG"
STRUCT_LOG_GATE_PROVIDER = "G6_PROVIDER_EVENTS"
TRACE_GATE = "G6_PROVIDER_TRACE"  # optional fine-grained stack inclusion
MAX_ERROR_MSG_CHARS = 300
MAX_TRACE_CHARS = 2000

_logger = logging.getLogger(__name__)

_truthy = {"1", "true", "yes", "on", "enabled", "y", "t"}


def _is_enabled() -> bool:
    env = os.getenv(STRUCT_LOG_GATE_GLOBAL, "").lower()
    if env in _truthy:
        return True
    env2 = os.getenv(STRUCT_LOG_GATE_PROVIDER, "").lower()
    return env2 in _truthy


def _trace_enabled() -> bool:
    return os.getenv(TRACE_GATE, "").lower() in _truthy


def _safe_now() -> float:
    try:
        return time.time()
    except Exception:  # pragma: no cover - extremely unlikely
        return 0.0


def _truncate(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _serialize(event: dict[str, Any]) -> str:
    try:
        return json.dumps(event, separators=(",", ":"), ensure_ascii=False)
    except Exception:  # pragma: no cover - never raise; fallback repr
        try:
            return json.dumps({"malformed_event_repr": repr(event)})
        except Exception:
            return "{\"event\":\"provider.kite.serialization_failure\"}"


def emit_provider_event(
    domain: str,
    action: str,
    outcome: str,
    *,
    start_ts: float | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a provider event immediately.

    Parameters:
        domain: logical area (e.g. "instruments", "quotes")
        action: operation (e.g. "fetch", "ltp")
        outcome: "success" | "error"
        start_ts: if provided, used to calculate duration; otherwise 0
        extra: optional additional stable scalar fields
    """
    if not _is_enabled():  # fast path
        return
    now = _safe_now()
    dur_ms = None
    if start_ts is not None and start_ts > 0:
        dur_ms = int((now - start_ts) * 1000)
    base = {
        "ts": now,
        "event": f"{PROVIDER_NAMESPACE}.{domain}.{action}.{outcome}",
        "namespace": PROVIDER_NAMESPACE,
        "domain": domain,
        "action": action,
        "outcome": outcome,
        "provider": PROVIDER_NAME,
        "thread": threading.current_thread().name,
        "pid": os.getpid(),
    }
    if dur_ms is not None:
        base["dur_ms"] = dur_ms
    if extra:
        # Avoid overriding base keys silently
        for k, v in extra.items():
            if k in base:
                base[f"extra_{k}"] = v
            else:
                base[k] = v
    try:
        _logger.info(_serialize(base))
    except Exception:  # pragma: no cover
        pass


@dataclass
class _ProviderEventCtx:
    domain: str
    action: str
    start_ts: float = field(default_factory=_safe_now)
    extra: dict[str, Any] = field(default_factory=dict)
    outcome: str | None = None
    error_type: str | None = None
    error_msg: str | None = None
    trace: str | None = None

    def add_field(self, key: str, value: Any) -> None:
        # Only retain JSON-serializable simple types; complex -> repr
        if isinstance(value, (str, int, float, bool)) or value is None:
            self.extra[key] = value
        else:
            self.extra[key] = repr(value)

    def mark_success(self) -> None:
        self.outcome = "success"

    def mark_error(self, exc: BaseException) -> None:
        self.outcome = "error"
        self.error_type = type(exc).__name__
        self.error_msg = _truncate(str(exc), MAX_ERROR_MSG_CHARS)
        if _trace_enabled():
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            self.trace = _truncate("".join(tb), MAX_TRACE_CHARS)

    # Context manager protocol
    def __enter__(self) -> _ProviderEventCtx:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        if not _is_enabled():  # skip all processing if disabled
            return False  # don't suppress exceptions
        if exc is not None:
            self.mark_error(exc)
        elif not self.outcome:
            # default implicit success
            self.outcome = "success"
        extra = dict(self.extra)
        if self.error_type:
            extra["error_type"] = self.error_type
        if self.error_msg:
            extra["error_msg"] = self.error_msg
        if self.trace:
            extra["trace"] = self.trace
        emit_provider_event(
            self.domain,
            self.action,
            self.outcome or "unknown",
            start_ts=self.start_ts,
            extra=extra,
        )
        # Never swallow exceptions
        return False


def provider_event(domain: str, action: str, **initial_fields: Any) -> _ProviderEventCtx:
    """Create a provider event context manager.

    The context always returns the event object so callers can
    incrementally add fields (counts, flags) or mark success explicitly.
    If disabled by gates, the context still executes but with a very
    cheap code path (branch + object instantiation) — acceptable for the
    few critical provider operations we intend to instrument.

    Example:
        with provider_event('quotes', 'ltp', symbol=symbol) as evt:
            price = _client.ltp(symbol)
            evt.add_field('price', price)
            # implicit success
            return price

    On exception, an error event is emitted (when enabled) containing
    error_type + truncated error_msg (and trace if TRACE gate set).
    """
    ctx = _ProviderEventCtx(domain=domain, action=action)
    for k, v in initial_fields.items():
        ctx.add_field(k, v)
    return ctx

__all__ = [
    "provider_event",
    "emit_provider_event",
    "PROVIDER_NAMESPACE",
    "PROVIDER_NAME",
    "STRUCT_LOG_GATE_GLOBAL",
    "STRUCT_LOG_GATE_PROVIDER",
    "TRACE_GATE",
]
