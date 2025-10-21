"""Structured JSON event logging utilities.

Provides a thin, dependency-light event emission helper that writes newline-
delimited JSON (NDJSON) records to a target log file (default
``logs/events.log``). This will later back panel updates and external tooling.

Design goals:
  * Non-blocking best-effort (IO errors swallowed after one log message)
  * Minimal allocations (reuse json.dumps on simple dict)
  * Backward compatible (safe no-op if directory missing; it will attempt create)

Environment overrides:
  * G6_EVENTS_LOG_PATH - explicit path to event log file
  * G6_EVENTS_DISABLE - if set to truthy => dispatch() becomes no-op

Event schema (baseline):
  ts: float (epoch seconds)
  event: str
  level: str (info|warn|error|debug)
  index: optional str
  expiry: optional str
  context: optional dict (must be JSON serializable)

Future extensions may add correlation ids, cycle counters, or host metadata.
"""
from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_io_suppressed = False  # once we hit a persistent IO error we stop spamming logs
_seq = 0  # monotonic sequence for emitted events (resets on process restart)
_cycle_correlation_id: str | None = None  # correlation id scoped to a cycle boundary
_metrics_counter = None  # lazily bound metrics counter (g6_events_emitted_total)
_min_level_rank = 0  # dynamic level threshold
_sampling_map: dict[str, float] = {}
_sampling_default: float = 1.0
_recent_buffer: list[str] = []  # raw JSON lines
_recent_buffer_max = 500

_LEVEL_RANK = {"debug": 10, "info": 20, "warn": 30, "warning": 30, "error": 40, "critical": 50}


def _log_path() -> str:
    override = os.environ.get("G6_EVENTS_LOG_PATH")
    if override:
        return override
    return os.path.join("logs", "events.log")


def events_enabled() -> bool:
    return os.environ.get("G6_EVENTS_DISABLE", "").lower() not in ("1", "true", "yes", "on")


def register_events_metrics(counter_obj: Any) -> None:
    """Register a metrics counter with signature counter(labels...) for events.

    Expected shape: counter_obj.labels(event="...").inc()
    This indirection avoids importing metrics layer inside events module at import time.
    """
    global _metrics_counter
    _metrics_counter = counter_obj


def set_cycle_correlation(correlation_id: str | None) -> None:
    """Set or clear the active cycle correlation id (propagated to subsequent events)."""
    global _cycle_correlation_id
    _cycle_correlation_id = correlation_id


def dispatch(event: str, *, level: str = "info", index: str | None = None,
             expiry: str | None = None, context: dict[str, Any] | None = None,
             correlation_id: str | None = None) -> None:
    """Emit a structured event line.

    Best-effort: failures to write after first warning are ignored silently.
    """
    if not events_enabled():  # fast path no-op
        return
    # Level filtering
    lvl = level.lower()
    rank = _LEVEL_RANK.get(lvl, 999)
    if rank < _min_level_rank:
        return
    # Sampling (per-event takes precedence, else default)
    rate = _sampling_map.get(event, _sampling_default)
    if rate <= 0:
        return
    if rate < 1.0 and random.random() > rate:
        return
    global _seq
    with _lock:
        _seq += 1
        seq_val = _seq
    record = {
        "ts": round(time.time(), 6),
        "event": event,
        "level": level,
        "seq": seq_val,
    }
    cid = correlation_id or _cycle_correlation_id
    if cid:
        record["correlation_id"] = cid
    if index is not None:
        record["index"] = index
    if expiry is not None:
        record["expiry"] = expiry
    if context:
        # Shallow copy to avoid accidental mutation after dispatch
        record["context"] = dict(context)
    line: str
    try:
        line = json.dumps(record, separators=(",", ":"))
    except Exception:  # pragma: no cover - defensive
        logger.exception("Failed to serialize event record")
        return
    global _io_suppressed
    path = _log_path()
    directory = os.path.dirname(path)
    try:
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
    except Exception:  # pragma: no cover
        if not _io_suppressed:
            logger.warning("[events] Unable to create directory for %s", path)
            _io_suppressed = True
        return
    try:
        with _lock:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            _recent_buffer.append(line)
            if len(_recent_buffer) > _recent_buffer_max:
                # drop oldest
                del _recent_buffer[0: len(_recent_buffer) - _recent_buffer_max]
        if _metrics_counter is not None:
            # Best-effort structural interaction: expect .labels(...).inc()
            try:
                labels_fn = getattr(_metrics_counter, 'labels', None)
                if callable(labels_fn):
                    inst = labels_fn(event=event)
                    inc_fn = getattr(inst, 'inc', None)
                    if callable(inc_fn):
                        inc_fn()
            except Exception:  # pragma: no cover
                logger.debug("events metric increment failed")
    except Exception:  # noqa
        if not _io_suppressed:
            logger.exception("[events] Failed writing event line; suppressing further errors")
            _io_suppressed = True

def configure_from_env() -> None:
    """Load filtering & sampling configuration from environment variables.

    G6_EVENTS_MIN_LEVEL: one of debug,info,warn,error (default: none -> debug)
    G6_EVENTS_SAMPLE_MAP: JSON object {"event_name": rate_float}
    G6_EVENTS_SAMPLE_DEFAULT: float rate applied when event not in map (default 1.0)
    G6_EVENTS_RECENT_MAX: integer max recent buffer size (default 500)
    """
    global _min_level_rank, _sampling_map, _sampling_default, _recent_buffer_max
    lvl = os.environ.get("G6_EVENTS_MIN_LEVEL", "debug").lower()
    _min_level_rank = _LEVEL_RANK.get(lvl, 0)
    try:
        raw_map = os.environ.get("G6_EVENTS_SAMPLE_MAP")
        if raw_map:
            _sampling_map = json.loads(raw_map)
    except Exception:  # pragma: no cover
        logger.warning("[events] Failed to parse G6_EVENTS_SAMPLE_MAP")
        _sampling_map = {}
    try:
        _sampling_default = float(os.environ.get("G6_EVENTS_SAMPLE_DEFAULT", "1.0"))
    except ValueError:
        _sampling_default = 1.0
    try:
        _recent_buffer_max = int(os.environ.get("G6_EVENTS_RECENT_MAX", str(_recent_buffer_max)))
    except ValueError:
        pass


def set_min_level(level: str) -> None:
    global _min_level_rank
    _min_level_rank = _LEVEL_RANK.get(level.lower(), 0)


def set_sampling(event: str, rate: float) -> None:
    _sampling_map[event] = rate


def set_default_sampling(rate: float) -> None:
    global _sampling_default
    _sampling_default = rate


def get_recent_events(limit: int = 50, include_context: bool = True) -> list[dict[str, Any]]:
    """Return newest events up to limit (reverse chronological).

    If include_context is False, drop 'context' field to reduce payload size.
    """
    if limit <= 0:
        return []
    with _lock:
        slice_lines = _recent_buffer[-limit:]
    out: list[dict[str, Any]] = []
    for ln in reversed(slice_lines):  # newest first
        try:
            obj = json.loads(ln)
            if not include_context and 'context' in obj:
                del obj['context']
            out.append(obj)
        except Exception:  # pragma: no cover
            continue
    return out


configure_from_env()  # initialize on import (safe defaults)

__all__ = [
    "dispatch",
    "events_enabled",
    "register_events_metrics",
    "set_cycle_correlation",
    "configure_from_env",
    "set_min_level",
    "set_sampling",
    "set_default_sampling",
    "get_recent_events",
]
