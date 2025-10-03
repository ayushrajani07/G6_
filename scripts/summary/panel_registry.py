"""Panel registry providing default panel providers for plain + rich rendering.

The intent is to unify panel data generation so both plain and rich renderers
consume identical structured content. Rich renderers can still choose to
provide more elaborate formatting later (Phase 2+).
"""
from __future__ import annotations
from typing import List, Sequence
from .panel_types import PanelData, PanelProvider
from .domain import SummaryDomainSnapshot

# --- Providers ---------------------------------------------------------------

class CyclePanelProvider:
    key = "cycle"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:  # pragma: no cover - thin
        c = snapshot.cycle
        lines = [
            f"cycle: {c.number if c.number is not None else '—'}",
            f"last_start: {c.last_start or '—'}",
            f"last_duration: {c.last_duration_sec:.3f}s" if c.last_duration_sec is not None else "last_duration: —",
            f"success_rate: {c.success_rate_pct:.2f}%" if c.success_rate_pct is not None else "success_rate: —",
        ]
        return PanelData(key=self.key, title="Cycle", lines=lines, meta={"number": c.number})

class IndicesPanelProvider:
    key = "indices"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:  # pragma: no cover - thin
        lines = [f"count: {len(snapshot.indices)}"] + [", ".join(snapshot.indices)[:120]] if snapshot.indices else ["count: 0"]
        return PanelData(key=self.key, title="Indices", lines=lines, meta={"count": len(snapshot.indices)})

class AlertsPanelProvider:
    key = "alerts"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:
        a = snapshot.alerts
        sev_parts = []
        if a.severities:
            for k, v in sorted(a.severities.items()):
                sev_parts.append(f"{k}:{v}")
        lines = [
            f"total: {a.total if a.total is not None else '—'}",
            f"by_severity: {' '.join(sev_parts) if sev_parts else '—'}",
        ]
        return PanelData(key=self.key, title="Alerts", lines=lines, meta={"total": a.total})

class ResourcesPanelProvider:
    key = "resources"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:
        r = snapshot.resources
        lines = [
            f"cpu_pct: {r.cpu_pct:.1f}" if r.cpu_pct is not None else "cpu_pct: —",
            f"memory_mb: {r.memory_mb:.1f}" if r.memory_mb is not None else "memory_mb: —",
        ]
        return PanelData(key=self.key, title="Resources", lines=lines, meta={"cpu_pct": r.cpu_pct, "memory_mb": r.memory_mb})

DEFAULT_PANEL_PROVIDERS: Sequence[PanelProvider] = (
    CyclePanelProvider(),
    IndicesPanelProvider(),
    AlertsPanelProvider(),
    ResourcesPanelProvider(),
)

def build_all_panels(snapshot: SummaryDomainSnapshot, providers: Sequence[PanelProvider] | None = None) -> List[PanelData]:
    out: List[PanelData] = []
    for p in providers or DEFAULT_PANEL_PROVIDERS:
        try:
            out.append(p.build(snapshot))
        except Exception as e:  # pragma: no cover - defensive
            out.append(PanelData(key=getattr(p, 'key', 'unknown'), title="ERROR", lines=[f"provider error: {e}"], meta={"error": True}))
    return out

__all__ = [
    "PanelData",
    "PanelProvider",
    "DEFAULT_PANEL_PROVIDERS",
    "build_all_panels",
    "CyclePanelProvider",
    "IndicesPanelProvider",
    "AlertsPanelProvider",
    "ResourcesPanelProvider",
]
