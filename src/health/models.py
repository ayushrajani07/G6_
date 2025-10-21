#!/usr/bin/env python3
"""
Lightweight health models and enums used across the platform.

No external deps; safe to import anywhere. This provides a minimal contract
for component/check health reporting and mapping to levels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Any


class HealthLevel(IntEnum):
    HEALTHY = 0
    DEGRADED = 1
    WARNING = 2
    CRITICAL = 3
    UNKNOWN = 4


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


def level_from_state(state: str | HealthState) -> HealthLevel:
    try:
        s = state.value if isinstance(state, HealthState) else str(state).lower()
    except Exception:
        s = "unknown"
    if s in ("healthy", "ok", "ready"):
        return HealthLevel.HEALTHY
    if s in ("degraded",):
        return HealthLevel.DEGRADED
    if s in ("warning", "warn"):
        return HealthLevel.WARNING
    if s in ("critical", "unhealthy", "error", "failed"):
        return HealthLevel.CRITICAL
    return HealthLevel.UNKNOWN


@dataclass
class ComponentHealth:
    name: str
    status: str = HealthState.UNKNOWN.value
    message: str = ""
    last_check: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> HealthLevel:
        return level_from_state(self.status)


@dataclass
class CheckHealth:
    name: str
    status: str = HealthState.UNKNOWN.value
    message: str = ""
    last_check: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def level(self) -> HealthLevel:
        return level_from_state(self.status)


@dataclass
class HealthResponse:
    timestamp: str
    status: str
    level: HealthLevel
    # Mapping or lists as simple structures (kept generic to avoid tight coupling)
    components: dict[str, ComponentHealth] | None = None
    checks: dict[str, CheckHealth] | None = None


__all__ = [
    "HealthLevel",
    "HealthState",
    "ComponentHealth",
    "CheckHealth",
    "HealthResponse",
    "level_from_state",
]
