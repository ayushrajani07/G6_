"""Domain snapshot models for the terminal dashboard refactor (Phase 0).

This module introduces typed immutable dataclasses that wrap the loose status
JSON structure currently consumed directly by layout/panel code. For Phase 0 we
perform only lightweight extraction; no behavioral change for existing code.

Future phases will migrate renderers and plugins to depend on these models
instead of raw dictionaries, enabling better testability and evolution.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# --- Domain Dataclasses -------------------------------------------------------

@dataclass(frozen=True)
class CycleInfo:
    number: int | None = None
    last_start: str | None = None  # ISO8601 string if available
    last_duration_sec: float | None = None
    success_rate_pct: float | None = None

@dataclass(frozen=True)
class AlertsInfo:
    total: int | None = None
    severities: Mapping[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class ResourceInfo:
    cpu_pct: float | None = None
    memory_mb: float | None = None

@dataclass(frozen=True)
class StorageInfo:
    lag: float | None = None  # generic backlog/lag seconds or units
    queue_depth: int | None = None
    last_flush_age_sec: float | None = None

@dataclass(frozen=True)
class PerfInfo:
    # Placeholder for performance counters (latencies, throughput)
    metrics: Mapping[str, float] = field(default_factory=dict)

@dataclass(frozen=True)
class CoverageInfo:
    indices_count: int | None = None

@dataclass(frozen=True)
class SummaryDomainSnapshot:
    ts_read: float
    raw: Mapping[str, Any]
    cycle: CycleInfo
    alerts: AlertsInfo
    resources: ResourceInfo
    storage: StorageInfo
    perf: PerfInfo
    coverage: CoverageInfo
    indices: list[str]

# --- Builder ------------------------------------------------------------------

def build_domain_snapshot(
    raw_status: Mapping[str, Any] | None,
    *,
    ts_read: float | None = None,
) -> SummaryDomainSnapshot:
    """Build a SummaryDomainSnapshot from a raw status mapping.

    Defensive: never raises; missing/invalid structures yield None fields.
    """
    if ts_read is None:
        ts_read = time.time()
    raw: Mapping[str, Any] = raw_status or {}

    # Extract indices (reuse simple logic here; later we can import derive.derive_indices safely)
    indices: list[str] = []
    try:
        src = raw.get("indices") or raw.get("symbols")  # type: ignore[attr-defined]
        if isinstance(src, list):
            indices = [str(s) for s in src]
        elif isinstance(src, str):
            indices = [s.strip() for s in src.split(',') if s.strip()]
        elif isinstance(src, dict):
            indices = [str(k) for k in src.keys()]
    except Exception:
        indices = []

    # Cycle extraction
    # Capture raw cycle first (numeric or structured) but allow loop overrides later.
    cycle_data = raw.get("cycle") or raw.get("last_cycle") or {}
    number: int | None = None
    last_start: str | None = None
    last_duration: float | None = None
    success_rate: float | None = None
    try:
        if isinstance(cycle_data, (int, float)):
            number = int(cycle_data)
        elif isinstance(cycle_data, dict):
            num_candidate = cycle_data.get("number") or cycle_data.get("cycle")
            if isinstance(num_candidate, (int, float)):
                number = int(num_candidate)
            last_start = cycle_data.get("start") or cycle_data.get("last_start")
            dur = cycle_data.get("duration") or cycle_data.get("last_duration")
            if isinstance(dur, (int, float)):
                last_duration = float(dur)
            sr = cycle_data.get("success_rate") or cycle_data.get("success_rate_pct")
            if isinstance(sr, (int, float)):
                success_rate = float(sr)
    except Exception:
        pass
    # Loop object may offer overrides
    try:
        loop_obj = raw.get("loop") if isinstance(raw, dict) else None
        if isinstance(loop_obj, dict):
            cyc_val = loop_obj.get("cycle")
            if isinstance(cyc_val, (int, float)):
                # Explicitly override even if number already set from simple raw cycle int
                number = int(cyc_val)
            lr_val = loop_obj.get("last_run")
            if last_start is None and isinstance(lr_val, str):
                last_start = lr_val
            ld_val = loop_obj.get("last_duration")
            if last_duration is None and isinstance(ld_val, (int, float)):
                last_duration = float(ld_val)
            sr_val = loop_obj.get("success_rate")
            if success_rate is None and isinstance(sr_val, (int, float)):
                success_rate = float(sr_val)
    except Exception:
        pass
    cycle = CycleInfo(
        number=number,
        last_start=last_start,
        last_duration_sec=last_duration,
        success_rate_pct=success_rate,
    )

    # Alerts
    alerts_total: int | None = None
    severities: dict[str, int] = {}
    try:
        alerts_obj = raw.get("alerts") if isinstance(raw, dict) else None
        if isinstance(alerts_obj, dict):
            total_candidate = alerts_obj.get("total") or alerts_obj.get("alerts_total")
            if isinstance(total_candidate, (int, float)):
                alerts_total = int(total_candidate)
            sev_obj = alerts_obj.get("severity_counts") or alerts_obj.get("severity") or {}
            if isinstance(sev_obj, dict):
                for k, v in sev_obj.items():
                    if isinstance(v, (int, float)):
                        severities[str(k)] = int(v)
    except Exception:
        pass
    alerts = AlertsInfo(total=alerts_total, severities=severities)

    # Resources (map to cpu & memory heuristics if present)
    cpu_pct: float | None = None
    memory_mb: float | None = None
    try:
        res_obj = raw.get("resources") if isinstance(raw, dict) else None
        if isinstance(res_obj, dict):
            cpu_candidate = res_obj.get("cpu_pct") or res_obj.get("cpu_percent")
            mem_candidate = res_obj.get("memory_mb") or res_obj.get("mem_mb") or res_obj.get("rss_mb")
            if isinstance(cpu_candidate, (int, float)):
                cpu_pct = float(cpu_candidate)
            if isinstance(mem_candidate, (int, float)):
                memory_mb = float(mem_candidate)
    except Exception:
        pass
    resources = ResourceInfo(cpu_pct=cpu_pct, memory_mb=memory_mb)

    # Storage extraction (best-effort)
    storage = StorageInfo()
    try:
        st_obj = raw.get("storage") if isinstance(raw, dict) else None
        if isinstance(st_obj, dict):
            lag = st_obj.get("lag") or st_obj.get("backlog")
            if isinstance(lag, (int, float)):
                lag_val: float = float(lag)
            else:
                lag_val = None  # type: ignore[assignment]
            depth = st_obj.get("queue_depth") or st_obj.get("pending")
            if not isinstance(depth, (int, float)):
                depth = None
            age = st_obj.get("last_flush_age") or st_obj.get("flush_age_sec")
            if not isinstance(age, (int, float)):
                age = None
            storage = StorageInfo(
                lag=lag_val,
                queue_depth=int(depth) if depth is not None else None,
                last_flush_age_sec=float(age) if age is not None else None,
            )
    except Exception:
        pass

    # Performance extraction (coarse)
    perf = PerfInfo()
    try:
        perf_obj = raw.get("performance") if isinstance(raw, dict) else None
        metrics: dict[str, float] = {}
        if isinstance(perf_obj, dict):
            for k, v in perf_obj.items():
                if isinstance(v, (int, float)):
                    metrics[str(k)] = float(v)
        if metrics:
            perf = PerfInfo(metrics=metrics)
    except Exception:
        pass

    coverage = CoverageInfo(indices_count=len(indices) if indices else None)

    return SummaryDomainSnapshot(
        ts_read=ts_read,
        raw=raw,
        cycle=cycle,
        alerts=alerts,
        resources=resources,
        coverage=coverage,
        storage=storage,
        perf=perf,
        indices=indices,
    )

__all__ = [
    "CycleInfo",
    "AlertsInfo",
    "ResourceInfo",
    "StorageInfo",
    "PerfInfo",
    "CoverageInfo",
    "SummaryDomainSnapshot",
    "build_domain_snapshot",
]
