"""Panel payload models used by the panels factory.

These types describe the JSON structures emitted to data/panels/*.json.
They intentionally remain loose (via Optional/Dict[Any, Any]) to preserve
backward compatibility with existing consumers (TUI/summary and tests).
"""
from __future__ import annotations

from typing import Any, TypedDict


class ProviderPanel(TypedDict, total=False):
    name: str | None
    auth: bool | None
    expiry: str | None
    latency_ms: float | None


class ResourcesPanel(TypedDict, total=False):
    cpu: float | None
    rss: int | None
    memory_mb: float | None


class LoopPanel(TypedDict, total=False):
    cycle: int | None
    last_start: str | None
    last_duration: float | None
    success_rate: float | None


class HealthPanel(TypedDict, total=False):
    # free-form dict of component->status
    # Using Dict[str, Any] to avoid over-constraining existing payloads
    pass


class IndicesSummaryPanel(TypedDict):
    # map index -> metrics
    # metrics: status, legs?, dq_score?, dq_issues?
    # Keep loose typing for compatibility
    # Example: { "NIFTY": {"status": "OK", "legs": 12, "dq_score": 99, "dq_issues": 0}, ... }
    # Represented as Dict[str, Dict[str, Any]]
    pass


class IndicesStreamItem(TypedDict, total=False):
    index: str
    status: str
    cycle: int | None
    time: str | None
    time_hms: str | None
    legs: int | None
    avg: float | None
    success: int | None
    dq_score: float | None
    dq_issues: int | None
    dq_labels: list[str] | None
    status_reason: str | None


PanelsDict = dict[str, Any]
