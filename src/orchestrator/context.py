"""Runtime context container for G6 orchestrator.

This lightweight dataclass centralizes objects that were previously threaded
implicitly through large function signatures or accessed via module-level
singletons inside `unified_main.py`.

Initial scope is intentionally minimal; it will expand as refactor proceeds.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class RuntimeContext:
    config: Any
    runtime_config: Any | None = None  # Phase 3: typed runtime_config snapshot (loop & metrics basics)
    metrics: Any | None = None
    providers: Any | None = None
    csv_sink: Any | None = None
    influx_sink: Any | None = None
    health_monitor: Any | None = None
    flags: dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    # Cooperative shutdown signal toggled by external handlers (e.g., signal handlers)
    shutdown: bool = False
    # Optional runtime status file path (if status snapshots enabled)
    runtime_status_file: str | None = None
    # Extracted loop state (populated progressively during refactor)
    index_params: dict[str, Any] | None = None
    readiness_ok: bool | None = None
    readiness_reason: str = ""
    cycle_count: int = 0
    # Cardinality / per-option metrics gating
    # When True, collectors should skip emitting per-option detailed metrics to limit series explosion
    per_option_metrics_disabled: bool = False
    # Cardinality guard last toggle timestamp (epoch seconds) for hysteresis evaluation
    cardinality_last_toggle: float | None = None
    # Per-index last successful collection timestamps (used for per-index data gap gauges)
    last_index_success_times: dict[str, float] = field(default_factory=dict)
    # Last cycle start timestamp (set by run_cycle; exposed explicitly to allow tests without monkeypatching slots)
    _last_cycle_start: float | None = None

    def flag(self, name: str, default: Any = None) -> Any:
        return self.flags.get(name, default)

    def set_flag(self, name: str, value: Any) -> None:
        self.flags[name] = value

__all__ = ["RuntimeContext"]
