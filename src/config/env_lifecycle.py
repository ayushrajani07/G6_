"""Environment variable lifecycle metadata (Phase 3).

Provides structured lifecycle classification for a curated subset of env vars.
This enables tooling & docs to reflect introduction/deprecation/removal status.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

__all__ = [
    "EnvLifecycle",
    "ENV_LIFECYCLE_REGISTRY",
    "to_json_snapshot",
]

@dataclass(frozen=True)
class EnvLifecycle:
    name: str
    status: str  # active|experimental|deprecated|removed
    introduced: str | None = None  # version or date
    deprecated: str | None = None
    removal_target: str | None = None
    replacement: str | None = None
    notes: str | None = None

ENV_LIFECYCLE_REGISTRY: list[EnvLifecycle] = [
    EnvLifecycle("G6_METRICS_ENABLED", "active", introduced="2024-Q4", notes="Canonical metrics enable flag"),
    EnvLifecycle("G6_METRICS_ENABLE", "deprecated", introduced="2024-Q2", deprecated="2025-Q1", removal_target="2025-Q4", replacement="G6_METRICS_ENABLED"),
    EnvLifecycle("G6_ALLOW_LEGACY_PANELS_BRIDGE", "deprecated", introduced="2024-Q3", deprecated="2025-Q2", removal_target="2025-Q4", notes="Panels bridge unification"),
    EnvLifecycle("G6_SUMMARY_LEGACY", "deprecated", introduced="2024-Q2", deprecated="2025-Q2", removal_target="2025-Q4"),
    EnvLifecycle("G6_REFACTOR_DEBUG", "experimental", introduced="2025-Q2"),
]

def to_json_snapshot() -> dict[str, object]:
    return {
        "generated": time.time(),
        "vars": [e.__dict__ for e in ENV_LIFECYCLE_REGISTRY],
    }
