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

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

PANEL_KEYS = [
    "header","indices","analytics","alerts","links","perfstore","storage","resources"
]

__all__ = ["PANEL_KEYS", "compute_all_panel_hashes"]


def _canonical(value: Any) -> Any:
    """Produce a JSON-serializable canonical form.

    Rules:
      - Floats: normalize -0.0 -> 0.0; NaN/Inf/-Inf to string sentinels.
      - Dicts: recurse, convert keys to str, sort by key.
      - Lists/Tuples/Sets: treat as list; recurse; result list order preserved for list/tuple,
        for sets we sort by JSON string form of each canonical element to remove nondeterminism.
      - Other scalars passed through.
    """
    # Float normalization
    if isinstance(value, float):
        if math.isnan(value):
            return "__NaN__"
        if math.isinf(value):
            return "__Inf__" if value > 0 else "__-Inf__"
        # normalize negative zero
        if value == 0.0:
            return 0.0
        # Coerce integral floats (e.g. 1.0) to int for canonical equivalence with literal ints
        if value.is_integer():
            try:
                return int(value)
            except Exception:
                return 0
        return value
    # Basic scalar types
    if value is None or isinstance(value, (str, int, bool)):
        return value
    # Mappings
    if isinstance(value, Mapping):
        items: Iterable = []
        try:
            items = value.items()  # type: ignore
        except Exception:
            items = []
        canon_items = []
        for k, v in items:
            try:
                sk = str(k)
            except Exception:
                sk = repr(k)
            canon_items.append((sk, _canonical(v)))
        # sort by key for determinism
        canon_items.sort(key=lambda kv: kv[0])
        return {k: v for k, v in canon_items}
    # Iterable containers
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    if isinstance(value, set):
        # sort set elements by their stable JSON representation to remove ordering issues
        canon_elems = [_canonical(v) for v in value]
        try:
            canon_elems.sort(key=lambda x: json.dumps(x, sort_keys=True, separators=(",", ":")))
        except Exception:
            canon_elems.sort(key=lambda x: repr(x))
        return canon_elems
    # Fallback: repr for unsupported objects
    try:
        return repr(value)
    except Exception:
        return "<unrepr>"


def _stable(obj: Any) -> str:
    try:
        return json.dumps(_canonical(obj), sort_keys=True, separators=(",", ":"))
    except Exception:
        return repr(obj)


def _sha(payload: Any) -> str:
    try:
        return hashlib.sha256(_stable(payload).encode("utf-8")).hexdigest()
    except Exception:
        return "err"


def compute_all_panel_hashes(status: Mapping[str, Any] | None, *, domain: Any | None = None) -> dict[str,str]:
    hashes: dict[str,str] = {}
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
        # Fallback: legacy tests mutate `resources` expecting perfstore hash drift.
        if not perf_obj and isinstance(status, Mapping) and isinstance(status.get("resources"), Mapping):
            # Select a small stable subset to avoid over-hashing transient noise.
            r = status.get("resources") or {}
            try:
                cpu = r.get("cpu") if isinstance(r, Mapping) else None
            except Exception:
                cpu = None
            if cpu is not None:
                perf_obj = {"cpu": cpu}
    hashes["perfstore"] = _sha(perf_obj)

    # storage
    storage_obj: dict[str, Any | None] | None
    if domain is not None and getattr(domain, 'storage', None) is not None:
        lag_v: Any | None = getattr(domain.storage, 'lag', None)
        qd_v: Any | None = getattr(domain.storage, 'queue_depth', None)
        age_v: Any | None = getattr(domain.storage, 'last_flush_age_sec', None)
        storage_obj = {
            "lag": lag_v if isinstance(lag_v, (int, float)) else None,
            "queue_depth": int(qd_v) if isinstance(qd_v, (int, float)) else None,
            "last_flush_age_sec": float(age_v) if isinstance(age_v, (int, float)) else None,
        }
    else:
        storage_obj = status.get("storage") if isinstance(status, Mapping) else None
    hashes["storage"] = _sha(storage_obj)

    # resources (lightweight: only include stable subset to avoid excessive churn)
    resources_obj = None
    if isinstance(status, Mapping):
        r = status.get("resources")
        if isinstance(r, Mapping):
            # pick common stable keys if present
            subset = {}
            for k in ("cpu", "cpu_pct", "memory_mb", "rss_mb"):
                v = r.get(k)
                if v is not None:
                    subset[k] = v
            if subset:
                resources_obj = subset
    hashes["resources"] = _sha(resources_obj)

    return hashes
