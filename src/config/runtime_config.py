"""Runtime configuration consolidation (Phase 2 skeleton).

This module provides a minimal, typed snapshot of a few frequently accessed
runtime parameters derived from environment variables. It does NOT replace the
existing comprehensive `config.loader` logic yet; it co-exists to enable gradual
adoption of a unified pattern (`get_runtime_config()`).

Rationale:
- Many modules read a small subset of loop/metrics env vars directly.
- Centralizing them reduces scattered os.getenv calls and paves the way for
  a frozen config object passed through `RuntimeContext`.

Scope (initial): loop interval, max cycles, metrics enable/port/host.
Future: extend with validated groups & feature flags once stable.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

__all__ = [
    "LoopSettings",
    "MetricsSettings",
    "RuntimeConfig",
    "get_runtime_config",
]

@dataclass(frozen=True)
class LoopSettings:
    interval_seconds: float
    max_cycles: int | None

@dataclass(frozen=True)
class MetricsSettings:
    enabled: bool
    host: str
    port: int

@dataclass(frozen=True)
class RuntimeConfig:
    loop: LoopSettings
    metrics: MetricsSettings

_singleton: RuntimeConfig | None = None

def _coerce_int(val: str | None) -> int | None:
    if val is None or not val.strip():
        return None
    try:
        return int(val)
    except Exception:
        return None

def _coerce_float(val: str | None, default: float) -> float:
    try:
        return float(val) if val and val.strip() else default
    except Exception:
        return default

def _coerce_bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() in {"1","true","yes","on"}

def build_runtime_config() -> RuntimeConfig:
    loop_interval = _coerce_float(os.getenv("G6_LOOP_INTERVAL_SECONDS"), 1.0)
    max_cycles = _coerce_int(os.getenv("G6_LOOP_MAX_CYCLES"))
    metrics_enabled = _coerce_bool(os.getenv("G6_METRICS_ENABLED") or os.getenv("G6_METRICS_ENABLE"), True)
    metrics_host = os.getenv("G6_METRICS_HOST", "0.0.0.0")
    try:
        metrics_port = int(os.getenv("G6_METRICS_PORT", "9108"))
    except Exception:
        metrics_port = 9108
    return RuntimeConfig(
        loop=LoopSettings(interval_seconds=loop_interval, max_cycles=max_cycles),
        metrics=MetricsSettings(enabled=metrics_enabled, host=metrics_host, port=metrics_port),
    )

def get_runtime_config(refresh: bool = False) -> RuntimeConfig:
    global _singleton
    if _singleton is None or refresh:
        _singleton = build_runtime_config()
    return _singleton
