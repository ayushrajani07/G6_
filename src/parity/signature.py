"""Parity signature helpers for legacy vs pipeline collector outputs.

Produces a reduced deterministic structure and stable SHA-256 signature.
Provides structured diff with categories.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from typing import Any

Float = float

DEFAULT_RTOL = float(os.getenv("G6_PARITY_FLOAT_RTOL", "1e-6"))
DEFAULT_ATOL = float(os.getenv("G6_PARITY_FLOAT_ATOL", "1e-9"))


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def build_reduced(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    """Extract stable structural + aggregate fields from a collector snapshot.

    Expected input keys (best-effort): indices, alerts, benchmark, memory, etc.
    Missing keys are tolerated; absent sections simply omitted.
    """
    reduced: dict[str, Any] = {}
    if snapshot is None:
        return reduced
    indices = snapshot.get("indices")
    if isinstance(indices, list):
        idx_list = []
        for ix in indices:
            if not isinstance(ix, dict):
                continue
            entry = {
                "index": ix.get("index"),
                "status": ix.get("status"),
                "option_count": ix.get("option_count"),
            }
            expiries = ix.get("expiries")
            if isinstance(expiries, list):
                # Count only expiries with >0 options
                count = 0
                for ex in expiries:
                    if isinstance(ex, dict):
                        raw_opts = ex.get("options")
                        if isinstance(raw_opts, (int, float)) and not isinstance(raw_opts, bool):
                            opts_f: float = float(raw_opts)
                            if opts_f > 0:
                                count += 1
                entry["expiry_count"] = count
            idx_list.append(entry)
        # Sort for determinism
        reduced["indices"] = sorted(idx_list, key=lambda d: d.get("index") or "")
        reduced["indices_count"] = len(idx_list)
        reduced["options_total"] = sum([e.get("option_count") or 0 for e in idx_list])
    alerts = snapshot.get("alerts")
    if isinstance(alerts, dict):  # some snapshots nest counts
        total = alerts.get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            reduced["alerts_total"] = int(total)
    elif isinstance(alerts, list):
        reduced["alerts_total"] = len(alerts)
    bench = snapshot.get("benchmark")
    if isinstance(bench, dict):
        # Only stable high-level fields
        for k in ("options_total", "anomalies", "anomaly_summary"):
            if k in bench:
                reduced[f"benchmark_{k}"] = bench[k] if k != "anomalies" else len(bench.get("anomalies") or [])
    mem = snapshot.get("memory")
    if isinstance(mem, dict):
        rss_candidate = mem.get("rss_mb") if _is_number(mem.get("rss_mb")) else mem.get("rss")
        if isinstance(rss_candidate, (int, float)) and not isinstance(rss_candidate, bool):
            reduced["memory_rss_mb"] = float(rss_candidate)
    # Phase 8: snapshot_summary (additive)
    snap_summary = snapshot.get("snapshot_summary") if isinstance(snapshot, Mapping) else None
    if isinstance(snap_summary, Mapping):
        for k in [
            "indices_count",
            "options_total",
            "expiries_total",
            "alerts_total",
            "indices_ok",
            "indices_empty",
        ]:
            if k in snap_summary and _is_number(snap_summary.get(k)):
                reduced[f"summary_{k}"] = snap_summary.get(k)
        pr_tot = snap_summary.get("partial_reason_totals")
        if isinstance(pr_tot, Mapping):
            # Normalize into stable list of tuples for hashing/diffing
            reduced["summary_partial_reason_keys"] = sorted(list(pr_tot.keys()))
            reduced["summary_partial_reason_total"] = sum(
                v for v in pr_tot.values() if _is_number(v)
            )
        # Grouped partial reasons (additive; ignore if absent for backward compat)
        pr_groups = snap_summary.get("partial_reason_groups")
        if isinstance(pr_groups, Mapping):
            # Record group keys + total counts per group for parity without deep nesting
            group_keys = sorted(list(pr_groups.keys()))
            reduced["summary_partial_reason_group_keys"] = group_keys
            for gk in group_keys:
                ginfo = pr_groups.get(gk)
                if isinstance(ginfo, Mapping):
                    total_val = ginfo.get("total")
                    if isinstance(total_val, (int, float)) and not isinstance(total_val, bool):
                        reduced[f"summary_group_{gk}_total"] = int(total_val)
    return reduced


def compute_signature(reduced: dict[str, Any]) -> str:
    payload = _canonical_json(reduced).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


# Diff categories: missing_section, extra_section, field_value_drift, set_size_mismatch, structural_mismatch
Diff = dict[str, Any]


def _float_close(a: Float, b: Float, *, rtol: float, atol: float) -> bool:
    return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)


def diff_reduced(a: dict[str, Any], b: dict[str, Any], *, rtol: float = DEFAULT_RTOL, atol: float = DEFAULT_ATOL) -> list[Diff]:
    diffs: list[Diff] = []
    # Section presence
    a_keys = set(a.keys())
    b_keys = set(b.keys())
    for k in sorted(a_keys - b_keys):
        diffs.append({"category": "extra_section", "section": k})
    for k in sorted(b_keys - a_keys):
        diffs.append({"category": "missing_section", "section": k})
    # Compare overlapping
    for k in sorted(a_keys & b_keys):
        va = a[k]
        vb = b[k]
        # Normalize numeric types early (int/float) to reduce false structural mismatches.
        if _is_number(va) and _is_number(vb):  # both numeric (int/float variants)
            if not _float_close(float(va), float(vb), rtol=rtol, atol=atol):
                diffs.append({"category": "field_value_drift", "field": k, "a": va, "b": vb})
            continue
        # Non-numeric type mismatch classification (preserve structural signal)
        if type(va) != type(vb):  # noqa: E721
            diffs.append({"category": "structural_mismatch", "field": k, "a_type": type(va).__name__, "b_type": type(vb).__name__})
            continue
        if isinstance(va, list):
            if not isinstance(vb, list):
                diffs.append({"category": "structural_mismatch", "field": k, "a_type": type(va).__name__, "b_type": type(vb).__name__})
                continue
            if len(va) != len(vb):
                diffs.append({"category": "set_size_mismatch", "field": k, "a_size": len(va), "b_size": len(vb)})
            else:
                # For indices list compare per-position dict fields
                for i, (ia, ib) in enumerate(zip(va, vb, strict=False)):
                    if isinstance(ia, dict) and isinstance(ib, dict):
                        for fk in ("index", "status", "option_count", "expiry_count"):
                            if ia.get(fk) != ib.get(fk):
                                diffs.append({"category": "field_value_drift", "field": f"{k}[{i}].{fk}", "a": ia.get(fk), "b": ib.get(fk)})
        else:
            if va != vb:
                diffs.append({"category": "field_value_drift", "field": k, "a": va, "b": vb})
    return diffs


__all__ = [
    "build_reduced",
    "compute_signature",
    "diff_reduced",
]
