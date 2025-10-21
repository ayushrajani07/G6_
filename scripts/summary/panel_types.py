"""Panel data types for Phase 1 renderer decoupling.

These types provide an intermediate representation between the domain snapshot
and specific render targets (Rich panels, plain text tables, JSON panels).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PanelData:
    """Generic representation of a panel's content.

    Fields:
    - key: stable logical panel name (e.g., 'cycle', 'alerts')
    - title: human readable header (may be omitted in compact modes)
    - lines: sequence of pre-formatted textual lines (plain mode); richer renderers can reformat
    - meta: optional structured metadata (counts, severity stats) for downstream decisions
    """
    key: str
    title: str
    lines: Sequence[str]
    meta: Mapping[str, Any] | None = None

class PanelProvider(Protocol):
    key: str
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData: ...  # pragma: no cover - interface only

# Forward reference import hint (avoids runtime import cycle)
try:  # pragma: no cover
    from .domain import SummaryDomainSnapshot  # noqa: F401
except Exception:  # pragma: no cover
    pass

__all__ = ["PanelData", "PanelProvider"]
