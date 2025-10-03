"""Panel payload models used by the panels factory.

These types describe the JSON structures emitted to data/panels/*.json.
They intentionally remain loose (via Optional/Dict[Any, Any]) to preserve
backward compatibility with existing consumers (TUI/summary and tests).
"""
from __future__ import annotations
from typing import Dict, Any, Optional, TypedDict


class ProviderPanel(TypedDict, total=False):
    name: Optional[str]
    auth: Optional[bool]
    expiry: Optional[str]
    latency_ms: Optional[float]


class ResourcesPanel(TypedDict, total=False):
    cpu: Optional[float]
    rss: Optional[int]
    memory_mb: Optional[float]


class LoopPanel(TypedDict, total=False):
    cycle: Optional[int]
    last_start: Optional[str]
    last_duration: Optional[float]
    success_rate: Optional[float]


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
    cycle: Optional[int]
    time: Optional[str]
    time_hms: Optional[str]
    legs: Optional[int]
    avg: Optional[float]
    success: Optional[int]
    dq_score: Optional[float]
    dq_issues: Optional[int]
    dq_labels: Optional[list[str]]
    status_reason: Optional[str]


PanelsDict = Dict[str, Any]
