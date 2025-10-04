"""Centralized panel hashing (post Phase 6 consolidation).

Provides stable content hashes for summary panels used by:
 - Unified loop (attaches once per cycle to SummarySnapshot)
 - SSE publisher (diff + subset events)
 - TerminalRenderer / PanelsWriter diff suppression
 - Resync endpoints (baseline comparison)

Design principles:
 - Deterministic: JSON serialization with sorted keys and compact separators.
 - Resilient: On serialization or extraction failure returns placeholder 'err'.
 - Minimal surface: two public helpers compute_all_panel_hashes() and
   compute_single_panel_hash() (the latter currently internal usage only).
 - Domain-aware: If a unified domain snapshot is present, prefer its structured
   fields to avoid redundant re-derivation from raw status.

Backward compatibility: Legacy `scripts.summary.rich_diff.compute_panel_hashes`
will import and forward to this implementation until removed.
"""
from __future__ import annotations
from typing import Mapping, Any, Dict
import hashlib, json

PANEL_KEYS = [
    "header","indices","analytics","alerts","links","perfstore","storage"
]

__all__ = ["PANEL_KEYS", "compute_all_panel_hashes"]


def _stable(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"))
    except Exception:
        return repr(obj)


def _sha(payload: Any) -> str:
    try:
        return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()
    except Exception:
        return "err"


def compute_all_panel_hashes(status: Mapping[str, Any] | None, *, domain: Any | None = None) -> Dict[str,str]:
    hashes: Dict[str,str] = {}
    # indices list reused by multiple panels
    indices: list[str] = []
    try:
        if status and isinstance(status, Mapping):
            raw_idx = status.get("indices") or status.get("symbols")
            if isinstance(raw_idx, list):
                indices = [str(i) for i in raw_idx]
            elif isinstance(raw_idx, dict):
                indices = list(raw_idx.keys())
    except Exception:
        indices = []

    # header components
    try:
        version = None
        if status and isinstance(status.get("app"), Mapping):
            version = status.get("app", {}).get("version")
        cycle_num = getattr(getattr(domain, 'cycle', None), 'number', None) if domain is not None else None
        header_basis = {"idx": indices, "ver": version, "cycle": cycle_num}
        hashes["header"] = _sha(header_basis)
    except Exception:
        hashes["header"] = "err"

    hashes["indices"] = _sha(indices)

    # alerts
    alerts_obj = status.get("alerts") if isinstance(status, Mapping) else None
    hashes["alerts"] = _sha(alerts_obj)

    # analytics (raw status or domain future hook)
    analytics_obj = status.get("analytics") if isinstance(status, Mapping) else None
    hashes["analytics"] = _sha(analytics_obj)

    # links panel stable: determined by CLI args / env; keep static sentinel
    hashes["links"] = "static"

    # perfstore
    if domain is not None and getattr(domain, 'perf', None) is not None:
        perf_obj = getattr(domain.perf, 'metrics', None)
    else:
        perf_obj = status.get("performance") if isinstance(status, Mapping) else None
    hashes["perfstore"] = _sha(perf_obj)

    # storage
    if domain is not None and getattr(domain, 'storage', None) is not None:
        storage_obj = {
            "lag": getattr(domain.storage, 'lag', None),
            "queue_depth": getattr(domain.storage, 'queue_depth', None),
            "last_flush_age_sec": getattr(domain.storage, 'last_flush_age_sec', None),
        }
    else:
        storage_obj = status.get("storage") if isinstance(status, Mapping) else None
    hashes["storage"] = _sha(storage_obj)

    return hashes
