"""Panel registry providing default panel providers for plain + rich rendering.

The intent is to unify panel data generation so both plain and rich renderers
consume identical structured content. Rich renderers can still choose to
provide more elaborate formatting later (Phase 2+).
"""
from __future__ import annotations

import time
from collections.abc import Sequence

from .domain import SummaryDomainSnapshot
from .panel_types import PanelData, PanelProvider

# --- Providers ---------------------------------------------------------------

class CyclePanelProvider:
    key = "cycle"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:  # pragma: no cover - thin
        c = snapshot.cycle
        lines = [
            f"cycle: {c.number if c.number is not None else '—'}",
            f"last_start: {c.last_start or '—'}",
            (
                f"last_duration: {c.last_duration_sec:.3f}s"
                if c.last_duration_sec is not None
                else "last_duration: —"
            ),
            (
                f"success_rate: {c.success_rate_pct:.2f}%"
                if c.success_rate_pct is not None
                else "success_rate: —"
            ),
        ]
        return PanelData(
            key=self.key,
            title="Cycle",
            lines=lines,
            meta={"number": c.number},
        )

class IndicesPanelProvider:
    key = "indices"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:  # pragma: no cover - thin
        lines = (
            [f"count: {len(snapshot.indices)}"]
            + [", ".join(snapshot.indices)[:120]]
            if snapshot.indices
            else ["count: 0"]
        )
        return PanelData(
            key=self.key,
            title="Indices",
            lines=lines,
            meta={"count": len(snapshot.indices)},
        )

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
        return PanelData(
            key=self.key,
            title="Alerts",
            lines=lines,
            meta={"total": a.total},
        )

class ResourcesPanelProvider:
    key = "resources"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:
        r = snapshot.resources
        lines = [
            f"cpu_pct: {r.cpu_pct:.1f}" if r.cpu_pct is not None else "cpu_pct: —",
            f"memory_mb: {r.memory_mb:.1f}" if r.memory_mb is not None else "memory_mb: —",
        ]
        return PanelData(
            key=self.key,
            title="Resources",
            lines=lines,
            meta={"cpu_pct": r.cpu_pct, "memory_mb": r.memory_mb},
        )

class StoragePanelProvider:
    key = "storage"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:  # pragma: no cover - thin
        s = snapshot.storage
        lines = [
            (
                f"lag: {s.lag:.2f}" if isinstance(s.lag, (int, float)) else "lag: —"
            ),
            (
                f"queue_depth: {s.queue_depth}"
                if s.queue_depth is not None
                else "queue_depth: —"
            ),
            (
                f"last_flush_age_sec: {s.last_flush_age_sec:.2f}"
                if isinstance(s.last_flush_age_sec, (int, float))
                else "last_flush_age_sec: —"
            ),
        ]
        return PanelData(
            key=self.key,
            title="Storage",
            lines=lines,
            meta={
                "lag": s.lag,
                "queue_depth": s.queue_depth,
                "last_flush_age_sec": s.last_flush_age_sec,
            },
        )

class PerfPanelProvider:
    key = "perfstore"
    def build(self, snapshot: SummaryDomainSnapshot) -> PanelData:  # pragma: no cover - thin
        p = snapshot.perf
        metrics = getattr(p, 'metrics', {}) or {}
        # Render top few metrics deterministically sorted
        items = sorted(metrics.items())[:6]
        if not items:
            lines = ["metrics: —"]
        else:
            rendered = [f"{k}={v:.2f}" for k, v in items]
            lines = [", ".join(rendered)[:120]]
        return PanelData(
            key=self.key,
            title="Performance",
            lines=lines,
            meta={"count": len(metrics)},
        )

DEFAULT_PANEL_PROVIDERS: Sequence[PanelProvider] = (
    CyclePanelProvider(),
    IndicesPanelProvider(),
    AlertsPanelProvider(),
    ResourcesPanelProvider(),
    StoragePanelProvider(),
    PerfPanelProvider(),
)

# Failure backoff state (module-level; lightweight and reset on process restart)
_provider_failures: dict[str, int] = {}
_provider_cooldown_until: dict[str, float] = {}
_FAIL_THRESHOLD = 3
_COOLDOWN_SEC = 30.0  # can be tuned later or env driven

def _should_skip(pkey: str) -> bool:
    # Cooldown skip if threshold exceeded and still within cooldown window
    if pkey in _provider_cooldown_until:
        if time.time() < _provider_cooldown_until[pkey]:
            return True
        # Cooldown expired -> reset counters
        _provider_cooldown_until.pop(pkey, None)
        _provider_failures.pop(pkey, None)
    return False

def _record_failure(pkey: str) -> None:
    cnt = _provider_failures.get(pkey, 0) + 1
    _provider_failures[pkey] = cnt
    if cnt >= _FAIL_THRESHOLD:
        _provider_cooldown_until[pkey] = time.time() + _COOLDOWN_SEC

def build_all_panels(
    snapshot: SummaryDomainSnapshot,
    providers: Sequence[PanelProvider] | None = None,
) -> list[PanelData]:
    out: list[PanelData] = []
    for p in providers or DEFAULT_PANEL_PROVIDERS:
        pkey = getattr(p, 'key', 'unknown')
        if _should_skip(pkey):
            out.append(
                PanelData(
                    key=pkey,
                    title="ERROR",
                    lines=["provider suppressed (cooldown)"],
                    meta={"error": True, "cooldown": True},
                )
            )
            continue
        try:
            out.append(p.build(snapshot))
            # Success resets failure counter
            if pkey in _provider_failures:
                _provider_failures.pop(pkey, None)
        except Exception as e:  # pragma: no cover - defensive
            _record_failure(pkey)
            out.append(
                PanelData(
                    key=pkey,
                    title="ERROR",
                    lines=[f"provider error: {e}"],
                    meta={"error": True, "failures": _provider_failures.get(pkey, 0)},
                )
            )
    return out

def build_panels_subset(snapshot: SummaryDomainSnapshot, keys: Sequence[str]) -> list[PanelData]:
    """Build only the panels for the provided keys.

    Falls back to empty list if keys empty. Unknown keys are ignored.
    """
    if not keys:
        return []
    key_set = set(keys)
    out: list[PanelData] = []
    for prov in DEFAULT_PANEL_PROVIDERS:
        pkey = getattr(prov, 'key', None)
        if pkey in key_set:
            if pkey and _should_skip(pkey):
                out.append(
                    PanelData(
                        key=pkey,
                        title="ERROR",
                        lines=["provider suppressed (cooldown)"],
                        meta={"error": True, "cooldown": True},
                    )
                )
                continue
            try:
                out.append(prov.build(snapshot))
                if pkey in _provider_failures:
                    _provider_failures.pop(pkey, None)
            except Exception as e:  # pragma: no cover - defensive
                if pkey:
                    _record_failure(pkey)
                out.append(
                    PanelData(
                        key=pkey or 'unknown',
                        title="ERROR",
                        lines=[f"provider error: {e}"],
                        meta={"error": True, "failures": _provider_failures.get(pkey, 0)},
                    )
                )
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
    "StoragePanelProvider",
    "PerfPanelProvider",
    "build_panels_subset",
]
