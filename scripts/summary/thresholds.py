"""Central thresholds registry for terminal summary/dashboard components.

Provides a single source of truth for display & scoring thresholds used by
panels and (future) snapshot builder / scoring layers.

Override Mechanism:
- Environment variable G6_SUMMARY_THRESH_OVERRIDES may contain a JSON object.
  Example:
    export G6_SUMMARY_THRESH_OVERRIDES='{"dq.warn":82, "dq.error":68}'
- Keys use dot-notation <domain>.<name> matching the REGISTRY entries below.
- Types are validated / coerced (float/int/bool/str) based on default type.
- Unknown keys are ignored (logged once lazily when first accessed).

Access Patterns:
- from scripts.summary.thresholds import T
- Use T.get("dq.warn") or sugar helpers like T.dq_warn
- Attribute form maps dots to underscores; e.g. dq.warn -> dq_warn

Design Notes:
- Keep domains minimal to avoid brittle proliferation.
- Future scoring layer will layer dynamic penalty factors; those are *not* stored here.
- This module intentionally has *no* heavy imports (keep panel import overhead low).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from typing import Any

from scripts.summary.env_config import load_summary_env

_LOCK = threading.RLock()
_LOADED = False
_OVERRIDES: dict[str, Any] = {}
_UNKNOWN_LOGGED: set[str] = set()
_ALIAS_MAP: dict[str, str] = {}  # attribute_name -> registry key

# Core registry of default thresholds.
# NOTE: Adjusting these defaults should be accompanied by doc update & changelog entry.
REGISTRY: dict[str, Any] = {
    # Data Quality display bucket boundaries (percent)
    "dq.warn": 85.0,
    "dq.error": 70.0,
    # Indices stream staleness (seconds)
    "stream.stale.warn_sec": 60.0,
    "stream.stale.error_sec": 180.0,
    # (Future) memory / latency for scoring (placeholder values)
    "latency.p95.warn_frac": 1.10,  # p95/interval
    "latency.p95.error_frac": 1.40,
    # Placeholder memory tiers (RSS MB) – may be replaced by adaptive system values
    "mem.tier2.mb": 800.0,
    "mem.tier3.mb": 1200.0,
}

@dataclass(frozen=True)
class _ThresholdsAccessor:
    def get(self, key: str, default: Any | None = None) -> Any:
        _ensure_loaded()
        if key in _OVERRIDES:
            return _coerce_type(key, _OVERRIDES[key], REGISTRY.get(key))
        if key in REGISTRY:
            return REGISTRY[key]
        if key not in _UNKNOWN_LOGGED:
            logging.debug(f"[thresholds] Unknown key requested: {key}")
            _UNKNOWN_LOGGED.add(key)
        return default

    # Attribute sugar: dots -> underscores mapping
    def __getattr__(self, name: str) -> Any:  # pragma: no cover (simple mapping)
        _ensure_loaded()
        # Direct alias map hit first (precomputed to support complex names)
        if name in _ALIAS_MAP:
            return self.get(_ALIAS_MAP[name])
        dotted = name.replace("_", ".")
        return self.get(dotted)

T = _ThresholdsAccessor()

def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        # Build alias map before reading overrides so overrides share keys
        _ALIAS_MAP.clear()
        for k in REGISTRY.keys():
            attr = k.replace('.', '_')
            _ALIAS_MAP[attr] = k
        raw = None
        try:
            raw = load_summary_env().threshold_overrides_raw
        except Exception:
            raw = None
        # Fallback to direct environment lookup if summary env snapshot absent or empty
        if not raw:
            raw = os.getenv("G6_SUMMARY_THRESH_OVERRIDES")
        if raw:
            try:
                obj = json.loads(raw)
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if not isinstance(k, str):
                            continue
                        # Defer type coercion until access (store raw)
                        _OVERRIDES[k] = v
            except Exception as e:  # pragma: no cover - defensive
                logging.warning(f"[thresholds] Failed to parse overrides: {e}")
        _LOADED = True

def _coerce_type(key: str, value: Any, default: Any) -> Any:
    if default is None:
        return value
    try:
        if isinstance(default, bool):
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes", "on")
            if isinstance(value, (int, float)):
                return bool(value)
        if isinstance(default, int) and not isinstance(default, bool):
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str) and value.strip():
                return int(float(value.strip()))
        if isinstance(default, float):
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str) and value.strip():
                return float(value.strip())
        if isinstance(default, str):
            return str(value)
    except Exception:  # pragma: no cover - defensive
        return default
    return value

def dump_effective() -> dict[str, Any]:
    """Return merged effective thresholds (defaults + applied overrides)."""
    _ensure_loaded()
    eff = dict(REGISTRY)
    for k, v in _OVERRIDES.items():
        eff[k] = _coerce_type(k, v, REGISTRY.get(k))
    return eff

def reset_for_tests() -> None:  # pragma: no cover - only for test harness
    global _LOADED, _OVERRIDES, _UNKNOWN_LOGGED, _ALIAS_MAP
    with _LOCK:
        _LOADED = False
        _OVERRIDES = {}
        _UNKNOWN_LOGGED = set()
        # Rebuild alias map immediately so attribute access works even before first load
        _ALIAS_MAP = {k.replace('.', '_'): k for k in REGISTRY.keys()}

__all__ = ["T", "dump_effective", "reset_for_tests"]
