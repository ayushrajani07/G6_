"""Unified structured logging emitter for provider & collector domains.

Responsibilities:
 - Enforce event naming schema (regex validation)
 - Provide single API for structured event emission
 - Optional dual/legacy emission controlled by env flag
 - Lightweight per-process dedup for selected noisy events
 - Timing helper for phase durations

Schema Pattern (v1):
    (<domain>.)?<category>(.<action>)?(.<outcome>)?
Where typical expiry pipeline events follow:
    expiry.resolve.ok
    expiry.fetch.empty
    expiry.prefilter.applied
    expiry.validate.fail
    expiry.salvage.applied
    expiry.persist.fail
    expiry.coverage.metrics
    expiry.complete

Domains allowed (reserved): expiry, provider, pipeline, metrics
Outcomes (final token suggestions): ok|fail|applied|metrics|complete|empty

Environment Flags:
    G6_LOG_SCHEMA_COMPAT=1  -> emit legacy message string (pass-through format) in addition to structured
    G6_LOG_DEDUP_DISABLE=1  -> disable dedup layer entirely

NOTE: Actual legacy formatting injection is pluggable via set_legacy_formatter.
"""
from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_logger = logging.getLogger("g6.logemitter")

EVENT_RE = re.compile(r"^(expiry|provider|pipeline|metrics)\.[a-z0-9_]+(?:\.[a-z0-9_]+){0,2}$")
NOISY_EVENTS = {
    "expiry.fetch.empty",
    "expiry.fetch.count",
    "expiry.prefilter.applied",
}

_dedup_enabled = os.environ.get("G6_LOG_DEDUP_DISABLE", "").lower() not in {"1","true","yes","on"}
_compat_enabled = os.environ.get("G6_LOG_SCHEMA_COMPAT", "").lower() in {"1","true","yes","on"}

_dedup_cache: set[tuple[str, tuple[tuple[str,str],...]]] = set()
_legacy_formatter = None  # type: ignore[assignment]

def set_legacy_formatter(fn):  # pragma: no cover - rarely used configuration path
    """Install a callback legacy_formatter(event: str, fields: Dict[str, Any]) -> str.
    Used when dual emission is enabled. The function should return a legacy single-line string.
    """
    global _legacy_formatter
    _legacy_formatter = fn

def _normalize_fields(fields: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        try:
            if isinstance(v, (str, int, float)) or v is None:
                out[k] = v
            else:
                out[k] = repr(v)
        except Exception:  # pragma: no cover - defensive
            out[k] = "<unrepr>"
    return out

def _should_dedup(event: str, norm_items: tuple[tuple[str,str],...]) -> bool:
    if not _dedup_enabled:
        return False
    if event not in NOISY_EVENTS:
        return False
    key = (event, norm_items)
    if key in _dedup_cache:
        return True
    _dedup_cache.add(key)
    return False

def log_event(event: str, level: int = logging.INFO, /, **fields: Any) -> None:
    """Emit a structured event.

    Validation: raises ValueError if event schema invalid (in tests we want strictness).
    In production we log a warning and bail for invalid events to avoid crashing.
    """
    if not EVENT_RE.match(event):
        msg = f"invalid_log_event_schema event={event}"
        if 'PYTEST_CURRENT_TEST' in os.environ:
            raise ValueError(msg)
        _logger.warning(msg)
        return
    norm = _normalize_fields(fields)
    norm_items = tuple(sorted((k, str(v)) for k, v in norm.items()))
    if _should_dedup(event, norm_items):
        return
    _logger.log(level, "%s %s", event, " ".join(f"{k}={v}" for k, v in norm_items))
    if _compat_enabled and _legacy_formatter is not None:
        try:
            legacy_line = _legacy_formatter(event, norm)
            if legacy_line:
                _logger.log(level, legacy_line)
        except Exception:  # pragma: no cover - legacy emit should never fail pipeline
            _logger.debug("legacy_formatter.error event=%s", event)

@dataclass
class PhaseTimer:
    event_base: str
    phase: str
    ctx: Mapping[str, Any]
    level: int = logging.DEBUG
    started: float = 0.0

    def __enter__(self):  # noqa: D401
        self.started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        dt_ms = (time.perf_counter() - self.started) * 1000.0
        event = f"{self.event_base}.{self.phase}.metrics"
        fields = dict(self.ctx)
        fields["ms"] = f"{dt_ms:.2f}"
        if exc_type is not None:
            fields["exc"] = getattr(exc_type, "__name__", str(exc_type))
        log_event(event, self.level, **fields)

def log_phase_timing(base: str, phase: str, ms: float, **ctx: Any) -> None:
    log_event(f"{base}.{phase}.metrics", logging.DEBUG, ms=f"{ms:.2f}", **ctx)

__all__ = [
    "log_event",
    "log_phase_timing",
    "PhaseTimer",
    "set_legacy_formatter",
    "EVENT_RE",
]
