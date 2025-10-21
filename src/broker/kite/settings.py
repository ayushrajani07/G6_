"""Consolidated environment-derived settings for Kite provider (Phase 3).

This snapshot object reduces repeated os.environ lookups on hot paths.
Behavior must remain identical; only centralizing access.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_BOOL_TRUE = {"1","true","yes","on"}

def _b(val: str | None, default: bool=False) -> bool:
    if val is None:
        return default
    return val.strip().lower() in _BOOL_TRUE

@dataclass(slots=True)
class Settings:
    concise: bool
    kite_timeout_sec: float
    kite_instruments_timeout_sec: float
    kite_throttle_ms: int
    instrument_cache_ttl: float
    lean_mode: bool
    debug_short_ttl: bool
    trace_collector: bool
    quiet_mode: bool
    quiet_allow_trace: bool
    disable_prefilter: bool
    enable_nearest_expiry_fallback: bool
    enable_backward_expiry_fallback: bool


def load_settings() -> Settings:
    # Concise mode (replicates legacy logic: default on unless explicit off)
    raw_concise = os.environ.get("G6_CONCISE_LOGS")
    if raw_concise is None:
        concise = True
    else:
        concise = raw_concise.lower() not in ("0","false","no","off")
    kite_timeout = float(
        os.environ.get("G6_KITE_TIMEOUT")
        or os.environ.get("G6_KITE_TIMEOUT_SEC", "4.0")
        or "4.0"
    )
    # Instruments can legitimately take longer; allow a separate, higher default
    kite_instr_timeout = float(
        os.environ.get("G6_KITE_INSTRUMENTS_TIMEOUT_SEC")
        or os.environ.get("G6_KITE_TIMEOUT_SEC")
        or "8.0"
    )
    throttle_ms = int(os.environ.get("G6_KITE_THROTTLE_MS", "0") or "0")
    try:
        ttl = float(os.environ.get('G6_INSTRUMENT_CACHE_TTL', '600'))
    except Exception:
        ttl = 600.0
    lean_mode = _b(os.environ.get('G6_LEAN_MODE'), False)
    debug_short_ttl = _b(os.environ.get('G6_DEBUG_SHORT_TTL'), False)
    # Adjust TTL only if user did not explicitly set env and lean/debug flags active
    if 'G6_INSTRUMENT_CACHE_TTL' not in os.environ:
        if lean_mode:
            ttl = 60.0
        elif debug_short_ttl:
            ttl = 30.0
    trace_collector = _b(os.environ.get('G6_TRACE_COLLECTOR'), False)
    quiet_mode = os.environ.get('G6_QUIET_MODE') == '1'
    quiet_allow_trace = _b(os.environ.get('G6_QUIET_ALLOW_TRACE'), False)
    disable_prefilter = _b(os.environ.get('G6_DISABLE_PREFILTER'), False)
    enable_nearest = _b(os.environ.get('G6_ENABLE_NEAREST_EXPIRY_FALLBACK'), True)
    enable_backward = _b(os.environ.get('G6_ENABLE_BACKWARD_EXPIRY_FALLBACK'), True)
    return Settings(
        concise=concise,
        kite_timeout_sec=kite_timeout,
        kite_instruments_timeout_sec=kite_instr_timeout,
        kite_throttle_ms=throttle_ms,
        instrument_cache_ttl=ttl,
        lean_mode=lean_mode,
        debug_short_ttl=debug_short_ttl,
        trace_collector=trace_collector,
        quiet_mode=quiet_mode,
        quiet_allow_trace=quiet_allow_trace,
        disable_prefilter=disable_prefilter,
        enable_nearest_expiry_fallback=enable_nearest,
        enable_backward_expiry_fallback=enable_backward,
    )

__all__ = ["Settings", "load_settings"]
