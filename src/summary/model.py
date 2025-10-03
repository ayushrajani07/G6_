"""Summary model skeleton (Phase 2).

Defines typed structures representing the conceptual summary output independent
of any rendering (terminal, panels, JSON). Rendering layers will adapt these
structures; business logic should populate them from runtime state.

Scope kept intentionally light; extend incrementally as fields stabilize.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Optional

__all__ = [
    "AlertEntry",
    "IndexHealth",
    "SummarySnapshot",
]

@dataclass(frozen=True)
class AlertEntry:
    code: str
    message: str
    severity: str  # INFO/WARN/CRITICAL etc.
    index: Optional[str] = None
    meta: Dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class IndexHealth:
    index: str
    status: str  # e.g., "healthy", "degraded", "error"
    last_update_epoch: float
    success_rate_percent: float | None = None
    options_last_cycle: int | None = None
    atm_strike: float | None = None
    iv_repr: float | None = None
    meta: Dict[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class SummarySnapshot:
    generated_epoch: float
    cycle: int | None
    alerts: List[AlertEntry]
    indices: List[IndexHealth]
    meta: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "generated": self.generated_epoch,
            "cycle": self.cycle,
            "alerts": [a.__dict__ for a in self.alerts],
            "indices": [i.__dict__ for i in self.indices],
            "meta": self.meta,
        }
