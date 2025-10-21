from __future__ import annotations

"""UnifiedStatusSnapshot model (Phase 1 -> foundation).

Authoritative schema:
This module is the single source of truth for the unified summary data model
consumed by future renderers / plugins / exporters. All additions MUST happen
here (never ad‑hoc dict growth elsewhere) so downstream adapters can reason
about version drift deterministically.

Versioning guidance:
* Backward-compatible purely additive fields MAY keep the same SCHEMA_VERSION.
* Renames, type changes, semantic shifts REQUIRE a version bump + migration note.
* Removal of a field should be avoided; prefer deprecating (keep field nullable) first.

Planned upcoming fields (tracked via TODO anchors):
    - TODO(model:rolling_stats): RollingWindowStats (success_rate_5m, etc.)
    - TODO(model:sse_classification): last_event_type / event_counters for SSE diff/full
    - TODO(model:latency_breakdown): provider_latency_components structure (p95, p99)
    - TODO(model:curated_layout_meta): curated layout hints (e.g., highlight indices)

When implementing a planned TODO above:
    1. Add the dataclass / field below.
    2. Update SCHEMA_VERSION only if change is not purely additive.
    3. Append rationale to MIGRATION.md under a new heading "UnifiedStatusSnapshot <version>".
"""
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA_VERSION = 1

@dataclass
class IndexEntry:
    name: str
    legs: int | None = None
    dq_score: float | None = None
    dq_issues: int | None = None
    success_rate: float | None = None

@dataclass
class CycleInfo:
    number: int | None = None
    last_duration_sec: float | None = None
    success_rate_pct: float | None = None
    next_run_in_sec: float | None = None

@dataclass
class DQCounts:
    green: int = 0
    warn: int = 0
    error: int = 0
    warn_threshold: float = 85.0
    error_threshold: float = 70.0

@dataclass
class AdaptiveSummary:
    alerts_total: int = 0
    alerts_by_type: dict[str,int] = field(default_factory=dict)
    severity_counts: dict[str,int] = field(default_factory=dict)
    followups: list[dict[str,Any]] = field(default_factory=list)
    mode: str | None = None

@dataclass
class UnifiedStatusSnapshot:
    schema_version: int = SCHEMA_VERSION
    ts_epoch: float = field(default_factory=lambda: time.time())
    cycle: CycleInfo = field(default_factory=CycleInfo)
    market_status: str = "?"
    provider: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    indices: list[IndexEntry] = field(default_factory=list)
    dq: DQCounts = field(default_factory=DQCounts)
    adaptive: AdaptiveSummary = field(default_factory=AdaptiveSummary)
    provenance: dict[str,str] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    raw_ref: dict[str, Any] = field(default_factory=dict)  # slim raw subset for debugging

    def to_dict(self) -> dict[str, Any]:  # convenience
        return asdict(self)


def assemble_model_snapshot(*, runtime_status: dict[str, Any] | None, panels_dir: str | None = None, include_panels: bool = True, in_memory_panels: dict[str, Any] | None = None) -> tuple[UnifiedStatusSnapshot, dict[str, Any]]:
    """Return UnifiedStatusSnapshot (native builder) + diagnostics.

    Native emission path (Phase 2): builds the model directly from
    runtime_status + panels (filesystem or in-memory) without first materializing
    the legacy `UnifiedSnapshot`. For backward safety, if any unexpected error
    occurs in the native path we fall back to the adapter over the legacy
    assembler so existing behavior/tests are preserved.

    Precedence rules for source data:
      1. In-memory panels (SSE overrides) if provided
      2. Filesystem panels (when include_panels & panels_dir)
      3. Raw runtime_status content

    Diagnostics (`diag`): { 'warnings': [...], 'native': True|False }
    """
    diag: dict[str, Any] = {"warnings": [], "native": True}

    try:
        status = runtime_status if isinstance(runtime_status, dict) else {}
        model = UnifiedStatusSnapshot()
        model.raw_ref = {}  # will hold lightweight original parts for debug

        # --- Panels ingestion (mirrors snapshot.py precedence) ---
        panel_provider = panel_resources = panel_loop = panel_indices = panel_adaptive_alerts = None
        if include_panels and in_memory_panels:
            try:
                panel_provider = in_memory_panels.get('provider') if isinstance(in_memory_panels.get('provider'), dict) else None
                panel_resources = in_memory_panels.get('resources') if isinstance(in_memory_panels.get('resources'), dict) else None
                panel_loop = in_memory_panels.get('loop') if isinstance(in_memory_panels.get('loop'), dict) else None
                panel_indices = in_memory_panels.get('indices') if isinstance(in_memory_panels.get('indices'), dict) else None
                panel_adaptive_alerts = in_memory_panels.get('adaptive_alerts') if isinstance(in_memory_panels.get('adaptive_alerts'), dict) else None
                model.provenance['panels_source'] = 'memory'
            except Exception:
                diag['warnings'].append('panels_mem_failed')
        elif include_panels and panels_dir:
            try:
                from pathlib import Path
                pdir = Path(panels_dir)
                if pdir.exists():
                    def _read(p: str):
                        try:
                            with (pdir / p).open('r', encoding='utf-8') as f:
                                import json as _json
                                return _json.load(f)
                        except Exception:
                            return None
                    panel_provider = _read('provider.json')
                    panel_resources = _read('resources.json')
                    panel_loop = _read('loop.json')
                    panel_indices = _read('indices.json')
                    panel_adaptive_alerts = _read('adaptive_alerts.json')
                    model.provenance['panels_source'] = 'filesystem'
            except Exception:
                diag['warnings'].append('panels_fs_failed')

        # --- Market status ---
        try:
            mkt = status.get('market') if isinstance(status.get('market'), dict) else None
            if isinstance(mkt, dict):
                model.market_status = str(mkt.get('status', '?')).upper() or '?'
            else:
                model.market_status = '?'
        except Exception:
            diag['warnings'].append('market_parse_failed')

        # --- Cycle info (loop) with panel override for duration/success rate if missing ---
        try:
            loop = status.get('loop') if isinstance(status.get('loop'), dict) else None
            if loop:
                num = loop.get('cycle') or loop.get('number')
                if isinstance(num, (int, float)):
                    model.cycle.number = int(num)
                if isinstance(loop.get('last_duration'), (int, float)):
                    model.cycle.last_duration_sec = float(loop['last_duration'])
                if isinstance(loop.get('success_rate'), (int, float)):
                    model.cycle.success_rate_pct = float(loop['success_rate'])
                nr = loop.get('next_run_in_sec') or loop.get('next_run_in')
                if isinstance(nr, (int, float)):
                    model.cycle.next_run_in_sec = float(nr)
            if isinstance(panel_loop, dict):
                # Only fill blanks from panel
                if model.cycle.number is None and isinstance(panel_loop.get('cycle'), (int, float)):
                    model.cycle.number = int(panel_loop['cycle'])
                if model.cycle.last_duration_sec is None and isinstance(panel_loop.get('last_duration'), (int, float)):
                    model.cycle.last_duration_sec = float(panel_loop['last_duration'])
                if model.cycle.success_rate_pct is None and isinstance(panel_loop.get('success_rate'), (int, float)):
                    model.cycle.success_rate_pct = float(panel_loop['success_rate'])
                model.provenance['cycle'] = 'panels'
        except Exception:
            diag['warnings'].append('cycle_parse_failed')

        # --- Provider ---
        try:
            prov = panel_provider if isinstance(panel_provider, dict) else (status.get('provider') if isinstance(status.get('provider'), dict) else None)
            if isinstance(prov, dict):
                model.provider = {
                    'name': prov.get('name') or prov.get('primary'),
                    'latency_ms': prov.get('latency_ms'),
                    'auth_valid': (prov.get('auth') or {}).get('valid') if isinstance(prov.get('auth'), dict) else None,
                    'auth_expiry': (prov.get('auth') or {}).get('expiry') if isinstance(prov.get('auth'), dict) else None,
                }
                model.provenance['provider'] = 'panels' if prov is panel_provider else 'status'
        except Exception:
            diag['warnings'].append('provider_parse_failed')

        # --- Resources ---
        try:
            res_obj = panel_resources if isinstance(panel_resources, dict) else (status.get('resources') if isinstance(status.get('resources'), dict) else None)
            if isinstance(res_obj, dict):
                model.resources = dict(res_obj)
                model.provenance['resources'] = 'panels' if res_obj is panel_resources else 'status'
        except Exception:
            diag['warnings'].append('resources_parse_failed')

        # --- Indices: prefer panel indices else indices_detail ---
        try:
            source_indices = panel_indices if isinstance(panel_indices, dict) else (status.get('indices_detail') if isinstance(status.get('indices_detail'), dict) else {})
            out: list[IndexEntry] = []
            for name, info in (source_indices or {}).items():
                if not isinstance(info, dict):
                    continue
                legs = info.get('legs') or info.get('current_cycle_legs')
                if isinstance(legs, (int, float)):
                    legs_int: int | None = int(legs)
                else:
                    legs_int = None
                dq_score = None
                dq_issues = None
                dq = info.get('dq') if isinstance(info.get('dq'), dict) else None
                if isinstance(info.get('dq_score'), (int, float)):
                    dq_score = float(info['dq_score'])
                elif dq and isinstance(dq.get('score_percent'), (int, float)):
                    dq_score = float(dq['score_percent'])
                if isinstance(info.get('dq_issues'), (int, float)):
                    dq_issues = int(info['dq_issues'])
                elif dq and isinstance(dq.get('issues_total'), (int, float)):
                    dq_issues = int(dq['issues_total'])
                sr = info.get('success_rate')
                success_rate = float(sr) if isinstance(sr, (int, float)) else None
                out.append(IndexEntry(name=str(name), legs=legs_int, dq_score=dq_score, dq_issues=dq_issues, success_rate=success_rate))
            model.indices = out
            if out:
                model.provenance['indices'] = 'panels' if source_indices is panel_indices else 'status'
        except Exception:
            diag['warnings'].append('indices_merge_failed')

        # --- Adaptive alerts summary ---
        try:
            adapt = panel_adaptive_alerts if isinstance(panel_adaptive_alerts, dict) else None
            ad_summary = model.adaptive
            if adapt:
                total = adapt.get('total')
                if isinstance(total, int):
                    ad_summary.alerts_total = total
                by_type = adapt.get('by_type')
                if isinstance(by_type, dict):
                    ad_summary.alerts_by_type = by_type  # type: ignore[assignment]
                sev = adapt.get('severity_counts')
                if isinstance(sev, dict):
                    ad_summary.severity_counts = sev  # type: ignore[assignment]
                fu = adapt.get('followups_recent')
                if isinstance(fu, list):
                    ad_summary.followups = fu[-10:]
                model.provenance['adaptive'] = 'panels'
            else:
                alerts_val = status.get('alerts') if isinstance(status.get('alerts'), list) else []
                if alerts_val:
                    ad_summary.alerts_total = len(alerts_val)
                    model.provenance['adaptive'] = 'status'
        except Exception:
            diag['warnings'].append('adaptive_merge_failed')

        # --- DQ Classification ---
        try:
            warn_thr = float(os.getenv('G6_DQ_WARN_THRESHOLD', '85') or 85)
            err_thr = float(os.getenv('G6_DQ_ERROR_THRESHOLD', '70') or 70)
            dq_counts = DQCounts(warn_threshold=warn_thr, error_threshold=err_thr)
            for idx in model.indices:
                score = idx.dq_score
                if score is None:
                    continue
                if score < err_thr:
                    dq_counts.error += 1
                elif score < warn_thr:
                    dq_counts.warn += 1
                else:
                    dq_counts.green += 1
            model.dq = dq_counts
        except Exception:
            diag['warnings'].append('dq_summary_failed')

        # --- raw_ref lightweight capture (debug provenance) ---
        try:
            raw_subset: dict[str, Any] = {}
            for k in ('market','loop','provider','resources','indices_detail','alerts'):
                v = status.get(k) if isinstance(status, dict) else None
                if v is not None:
                    raw_subset[k] = v
            raw_subset['_panels_shadow'] = {
                'provider': bool(panel_provider),
                'resources': bool(panel_resources),
                'loop': bool(panel_loop),
                'indices': bool(panel_indices),
                'adaptive_alerts': bool(panel_adaptive_alerts),
            }
            model.raw_ref = raw_subset
        except Exception:
            pass

        return model, diag
    except Exception as e:
        # Native path failure now propagates minimal diag (adapter removed)
        return UnifiedStatusSnapshot(), {"warnings": ["native_fail"], "error": str(e), "native": False}

__all__ = [
    'UnifiedStatusSnapshot','IndexEntry','CycleInfo','DQCounts','AdaptiveSummary','assemble_model_snapshot'
]
