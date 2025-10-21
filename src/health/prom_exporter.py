#!/usr/bin/env python3
"""
Prometheus exporter for health data. Optional and lightweight.

This module exports 2 gauges:
 - g6_health_level{component="overall|<name>"} -> numeric HealthLevel value
 - g6_health_state_info{component="overall|<name>", state="..."} -> 1 for current, 0 otherwise

It doesn't start any HTTP server on its own; integrate with the existing metrics server.
"""
from __future__ import annotations

from typing import Any, cast

_PromGauge: Any | None
try:  # optional dependency; safe fallback when missing
    from prometheus_client import Gauge as _PromGauge
except Exception:  # pragma: no cover - metrics optional
    _PromGauge = None

from .models import HealthLevel, HealthState


class HealthMetricsExporter:
    def __init__(self, namespace: str = "g6") -> None:
        self._enabled = _PromGauge is not None
        if not self._enabled:
            self._level_g: Any | None = None
            self._state_info_g: Any | None = None
            return
        pg = cast(Any, _PromGauge)
        self._level_g = pg(
            f"{namespace}_health_level",
            "Numeric health level (0 healthy .. 4 unknown)",
            ["component"],
        )
        self._state_info_g = pg(
            f"{namespace}_health_state_info",
            "Info metric exposing the current health state per component",
            ["component", "state"],
        )

    def enabled(self) -> bool:
        return bool(self._enabled)

    def set_overall(self, level: HealthLevel, state: HealthState | str) -> None:
        if not self._enabled:
            return
        comp = "overall"
        lvl = cast(Any, self._level_g)
        lvl.labels(component=comp).set(int(level))
        self._mark_state(comp, state)

    def set_component(self, name: str, level: HealthLevel, state: HealthState | str) -> None:
        if not self._enabled:
            return
        lvl = cast(Any, self._level_g)
        lvl.labels(component=name).set(int(level))
        self._mark_state(name, state)

    def bulk_set_components(self, mapping: dict[str, dict[str, int | str]]) -> None:
        """
        mapping: {name: {"level": int(HealthLevel), "state": str}}
        """
        if not self._enabled:
            return
        for name, data in mapping.items():
            raw_level = data.get("level", int(HealthLevel.UNKNOWN))
            level: int
            if isinstance(raw_level, int):
                level = raw_level
            else:
                try:
                    level = int(raw_level)  # raw_level could be str/float convertible
                except Exception:
                    level = int(HealthLevel.UNKNOWN)
            raw_state = data.get("state", HealthState.UNKNOWN.value)
            if isinstance(raw_state, HealthState):
                state = raw_state.value
            else:
                try:
                    state = str(raw_state)
                except Exception:
                    state = HealthState.UNKNOWN.value
            lvl = cast(Any, self._level_g)
            lvl.labels(component=name).set(level)
            self._mark_state(name, state)

    # Internal helpers
    def _mark_state(self, component: str, state: HealthState | str) -> None:
        if not self._enabled:
            return
        s = state.value if isinstance(state, HealthState) else str(state)
        for candidate in (
            HealthState.HEALTHY.value,
            HealthState.DEGRADED.value,
            HealthState.WARNING.value,
            HealthState.CRITICAL.value,
            HealthState.UNKNOWN.value,
        ):
            si = cast(Any, self._state_info_g)
            si.labels(component=component, state=candidate).set(
                1 if candidate == s else 0
            )


__all__ = ["HealthMetricsExporter"]
