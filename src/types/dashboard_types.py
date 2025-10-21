"""Typed structures and protocols for dashboard and panel typing.

Centralizes common TypedDicts / Protocols used across metrics cache, panel updater,
and FastAPI dashboard app to reduce widespread Dict[str, Any] usage.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    ContextManager,
    Literal,
    Protocol,
    TypedDict,
    runtime_checkable,
)

# -------------------- Panel / Metrics Row Structures --------------------

class StreamRow(TypedDict):
    time: str
    index: str
    legs: int
    legs_avg: int | None
    legs_cum: int | None
    succ: float | None
    succ_avg: float | None
    succ_life: float | None
    cycle_attempts: float | None
    err: str
    status: str
    status_reason: str

class FooterSummary(TypedDict):
    total_legs: int
    overall_success: float | None
    indices: int

class CsvStorage(TypedDict, total=False):
    files_total: float | None
    records_total: float | None
    records_delta: float | None
    errors_total: float | None
    disk_mb: float | None

class InfluxStorage(TypedDict, total=False):
    points_total: float | None
    points_delta: float | None
    write_success_pct: float | None
    connection: float | None
    query_latency_ms: float | None

class BackupStorage(TypedDict, total=False):
    files_total: float | None
    last_backup_unixtime: float | None
    age_seconds: float | None
    size_mb: float | None

class StorageSnapshot(TypedDict):
    csv: CsvStorage
    influx: InfluxStorage
    backup: BackupStorage

class ErrorEvent(TypedDict):
    index: str
    error_type: str
    delta: float
    ago: float
    ts: float

# -------------------- Panel Payload Root Types --------------------
class IndicesStreamPanel(TypedDict):
    kind: Literal['indices_stream']
    items: list[StreamRow]

class StoragePanel(TypedDict):
    kind: Literal['storage']
    storage: StorageSnapshot

class FooterPanel(TypedDict):
    kind: Literal['footer']
    footer: FooterSummary

class MemorySnapshot(TypedDict, total=False):
    rss_mb: float | None
    peak_rss_mb: float | None
    gc_collections_total: int | None
    gc_last_duration_ms: float | None

# -------------------- Unified Endpoint Models (Optional) --------------------
class UnifiedStatusCore(TypedDict, total=False):
    uptime_seconds: float | None
    avg_cycle_time: float | None
    options_per_minute: float | None
    collection_success_pct: float | None
    api_success_pct: float | None

class UnifiedStatusResources(TypedDict, total=False):
    cpu_pct: float | None
    memory_mb: float | None

class UnifiedStatusAdaptive(TypedDict, total=False):
    memory_pressure_level: float | None
    depth_scale: float | None

class UnifiedStatusIndexEntry(TypedDict, total=False):
    index: str
    options_processed: float | None
    last_collection: float | None
    success_pct: float | None
    # pcr may be a nested mapping expiry->value; type loosely here
    pcr: Mapping[str, float] | None

class UnifiedStatusResponse(TypedDict, total=False):
    ts: float
    age_seconds: float | None
    stale: bool | None
    core: UnifiedStatusCore
    resources: UnifiedStatusResources
    adaptive: UnifiedStatusAdaptive
    indices: list[UnifiedStatusIndexEntry]

class UnifiedIndicesResponse(TypedDict, total=False):
    # shape is dynamic; we keep loose to allow provider-dependent keys
    indices: Mapping[str, Any] | None

class UnifiedSourceStatusResponse(TypedDict, total=False):
    # underlying source status (provider-specific); keep loose
    status: Mapping[str, Any] | None

# History entries may contain partial subsets (errors OR storage). We model a loose shape.
class HistoryErrors(TypedDict):
    kind: Literal['errors']
    errors: Mapping[str, float]

class HistoryStorage(TypedDict):
    kind: Literal['storage']
    storage: StorageSnapshot

HistoryEntry = HistoryErrors | HistoryStorage  # discriminated by 'kind'

# -------------------- Rolling State --------------------
class RollState(TypedDict):
    legs_total: float
    legs_cycles: int
    succ_total: float
    succ_cycles: int
    last_err_ts: float
    last_err_type: str

# -------------------- Protocols --------------------
@runtime_checkable
class UnifiedSourceProtocol(Protocol):
    def get_runtime_status(self) -> Mapping[str, Any]: ...
    def get_indices_data(self) -> Mapping[str, Any]: ...
    def get_source_status(self) -> Mapping[str, Any]: ...

@runtime_checkable
class PanelsTransaction(Protocol):
    def __enter__(self) -> object: ...
    def __exit__(self, exc_type, exc, tb) -> bool | None: ...

@runtime_checkable
class OutputRouterProtocol(Protocol):
    def begin_panels_txn(self) -> ContextManager[object]: ...
    def panel_update(self, name: str, payload: Mapping[str, Any], *, kind: str | None = None) -> None: ...
    def panel_append(self, name: str, item: Mapping[str, Any], *, cap: int | None = None, kind: str | None = None) -> None: ...

@runtime_checkable
class ErrorHandlerProtocol(Protocol):
    def handle_error(
        self,
        exception: Exception,
        category: Any = ...,
        severity: Any = ...,
        component: str = ...,
        function_name: str = ...,
        message: str = ...,
        context: Mapping[str, Any] | None = ...,
        should_log: bool = ...,
        should_reraise: bool = ...,
    ) -> Any: ...

# Convenience re-export list for __all__
__all__ = [
    'StreamRow','FooterSummary','CsvStorage','InfluxStorage','BackupStorage','StorageSnapshot',
    'ErrorEvent','HistoryErrors','HistoryStorage','HistoryEntry','RollState',
    'UnifiedSourceProtocol','OutputRouterProtocol','PanelsTransaction'
]
