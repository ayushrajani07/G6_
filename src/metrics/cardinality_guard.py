"""Cardinality guard for grouped metrics.

Provides optional runtime detection of unexpected metric count growth per
group relative to a recorded baseline snapshot.

Environment Variables
---------------------
G6_CARDINALITY_SNAPSHOT   : Path to write (or overwrite) JSON baseline and exit guard early.
G6_CARDINALITY_BASELINE   : Path to existing JSON baseline to compare against.
G6_CARDINALITY_ALLOW_GROWTH_PERCENT : Integer/float percent allowed growth per group (default 10).
G6_CARDINALITY_FAIL_ON_EXCESS       : When truthy, raise RuntimeError if any group exceeds allowed growth.

Baseline JSON Schema (version=1)
--------------------------------
{
  "version": 1,
  "generated": "2025-10-02T12:34:56Z",
  "groups": { "analytics_vol_surface": ["vol_surface_rows", ...] }
}

Returned Summary (also attached to registry as _cardinality_guard_summary):
{
  'baseline_path': str|None,
  'snapshot_written': bool,
  'allowed_growth_percent': float,
  'offenders': [ { 'group': str, 'baseline': int, 'current': int, 'growth_percent': float } ],
  'total_groups': int,
  'evaluated_groups': int,
  'new_groups': [str],
}

Future Extensions (Roadmap): sample (series) count tracking, per-metric label
cardinality heuristics, anomaly scoring.
"""
from __future__ import annotations

from typing import Any, Dict, List
import json, os, logging, datetime as _dt

logger = logging.getLogger(__name__)


def _parse_bool(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:  # pragma: no cover - trivial
    # Use timezone-aware UTC (utcnow() deprecated) and emit Z suffix.
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def build_current_mapping(reg: Any) -> Dict[str, List[str]]:
    groups = getattr(reg, "_metric_groups", {})  # attr -> group
    mapping: Dict[str, List[str]] = {}
    for attr, grp in groups.items():
        mapping.setdefault(grp, []).append(attr)
    for grp, attrs in mapping.items():
        attrs.sort()
    return mapping


def write_snapshot(path: str, mapping: Dict[str, List[str]]):
    data = {
        "version": 1,
        "generated": _now_iso(),
        "groups": mapping,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except Exception as e:  # pragma: no cover - IO error path
        logger.error("cardinality.snapshot.write_failed path=%s err=%s", path, e)


def load_baseline(path: str) -> Dict[str, List[str]] | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        groups = data.get("groups")
        if not isinstance(groups, dict):
            return None
        cleaned: Dict[str, List[str]] = {}
        for g, arr in groups.items():
            if isinstance(g, str) and isinstance(arr, list):
                cleaned[g] = [a for a in arr if isinstance(a, str)]
        return cleaned
    except FileNotFoundError:
        logger.warning("cardinality.baseline.missing path=%s", path)
    except Exception as e:  # pragma: no cover - parse error
        logger.warning("cardinality.baseline.load_failed path=%s err=%s", path, e)
    return None


def check_cardinality(reg: Any) -> dict | None:
    """Main entrypoint invoked from MetricsRegistry (optional).

    Decides behavior based on env variables (snapshot vs compare). Always
    attaches summary (even on snapshot-only path) to registry for tests.
    """
    snap_path = os.getenv("G6_CARDINALITY_SNAPSHOT", "").strip()
    base_path = os.getenv("G6_CARDINALITY_BASELINE", "").strip()
    if not snap_path and not base_path:
        return None  # guard inactive

    allow_pct_raw = os.getenv("G6_CARDINALITY_ALLOW_GROWTH_PERCENT", "10").strip()
    try:
        allow_pct = float(allow_pct_raw)
    except ValueError:
        allow_pct = 10.0
    fail = _parse_bool(os.getenv("G6_CARDINALITY_FAIL_ON_EXCESS"))

    mapping = build_current_mapping(reg)

    summary: dict = {
        "baseline_path": base_path or None,
        "snapshot_written": False,
        "allowed_growth_percent": allow_pct,
        "offenders": [],
        "total_groups": len(mapping),
        "evaluated_groups": 0,
        "new_groups": [],
    }

    # Snapshot mode takes precedence (allows generating a baseline without comparison)
    if snap_path:
        try:
            write_snapshot(snap_path, mapping)
            summary["snapshot_written"] = True
            logger.info("metrics.cardinality.snapshot_written path=%s groups=%d", snap_path, len(mapping))
        except Exception:  # pragma: no cover
            pass
        # If only snapshot (no baseline) we stop here
        if not base_path:
            return summary

    baseline = load_baseline(base_path) if base_path else None
    if not baseline:
        logger.info("metrics.cardinality.guard_skipped reason=no_baseline")
        return summary

    offenders = []
    new_groups = []
    for grp, current_attrs in mapping.items():
        base_attrs = baseline.get(grp)
        if base_attrs is None:
            new_groups.append(grp)
            # treat as growth beyond threshold automatically
            offenders.append({
                "group": grp,
                "baseline": 0,
                "current": len(current_attrs),
                "growth_percent": 100.0 if current_attrs else 0.0,
            })
            continue
        baseline_count = len(base_attrs)
        current_count = len(current_attrs)
        growth_pct = 0.0
        if baseline_count == 0:
            growth_pct = 100.0 if current_count > 0 else 0.0
        elif current_count > baseline_count:
            growth_pct = ((current_count - baseline_count) / baseline_count) * 100.0
        # Only evaluate groups present in baseline (for evaluated count)
        summary["evaluated_groups"] += 1
        if growth_pct > allow_pct:
            offenders.append({
                "group": grp,
                "baseline": baseline_count,
                "current": current_count,
                "growth_percent": round(growth_pct, 2),
            })
    summary["offenders"] = offenders
    summary["new_groups"] = sorted(new_groups)

    if offenders:
        level = logging.ERROR if fail else logging.WARNING
        try:
            logger.log(level, "metrics.cardinality.guard offenders=%d allow=%.2f", len(offenders), allow_pct, extra={
                "event": "metrics.cardinality.guard",
                "offenders": offenders[:5],  # cap inline payload
                "allowed_growth_percent": allow_pct,
            })
        except Exception:
            pass
        if fail:
            raise RuntimeError(f"Cardinality growth exceeded threshold (offenders={len(offenders)})")
    else:
        logger.info("metrics.cardinality.guard_ok evaluated=%d", summary["evaluated_groups"])
    return summary


__all__ = ["check_cardinality"]
