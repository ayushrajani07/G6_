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

import datetime as _dt
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _parse_bool(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:  # pragma: no cover - trivial
    # Use timezone-aware UTC (utcnow() deprecated) and emit Z suffix.
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def build_current_mapping(reg: Any) -> dict[str, list[str]]:
    groups = getattr(reg, "_metric_groups", {})  # attr -> group
    mapping: dict[str, list[str]] = {}
    for attr, grp in groups.items():
        mapping.setdefault(grp, []).append(attr)
    for grp, attrs in mapping.items():
        attrs.sort()
    return mapping


def write_snapshot(path: str, mapping: dict[str, list[str]]):
    data = {
        "version": 1,
        "generated": _now_iso(),
        "groups": mapping,
    }
    # Write atomically to reduce risk of readers encountering truncated JSON (test parallelism / fast follow reads)
    try:
        import os
        import tempfile
        dir_name = os.path.dirname(path) or "."
        fd, tmp_path = tempfile.mkstemp(prefix="._card_snap_", dir=dir_name, text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
                f.flush()
                try:
                    os.fsync(f.fileno())  # ensure durability before rename
                except Exception:
                    pass
            # On Windows replace target if exists (os.replace is atomic when same volume)
            os.replace(tmp_path, path)
        except Exception:
            # Cleanup temp file on failure path
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise
    except Exception as e:  # pragma: no cover - IO error path
        logger.error("cardinality.snapshot.write_failed path=%s err=%s", path, e)


def load_baseline(path: str) -> dict[str, list[str]] | None:
    import time as _t
    attempts = 3
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return None
            groups = data.get("groups")
            if not isinstance(groups, dict):
                return None
            cleaned: dict[str, list[str]] = {}
            for g, arr in groups.items():
                if isinstance(g, str) and isinstance(arr, list):
                    cleaned[g] = [a for a in arr if isinstance(a, str)]
            return cleaned
        except FileNotFoundError:
            logger.warning("cardinality.baseline.missing path=%s", path)
            break
        except Exception as e:  # pragma: no cover - parse error / transient partial write
            last_err = e
            if i < attempts - 1:
                _t.sleep(0.05)
                continue
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
            # Fallback: if file unexpectedly zero-length (pre-created & write replaced failed silently), attempt simple rewrite
            try:
                if os.path.exists(snap_path) and os.path.getsize(snap_path) == 0:
                    with open(snap_path, 'w', encoding='utf-8') as _fw:
                        json.dump({"version":1, "generated": _now_iso(), "groups": mapping}, _fw, indent=2, sort_keys=True)
                        _fw.flush()
            except Exception:
                pass
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

    # --- Emit guard diagnostic metrics via generated accessors (best-effort) ---
    try:  # encapsulate failures so guard doesn't break application
        from src.metrics import generated as _g  # type: ignore
        # Simple gauges
        if hasattr(_g, 'm_cardinality_guard_offenders_total'):
            g = _g.m_cardinality_guard_offenders_total()
            if g: g.set(len(offenders))  # type: ignore[attr-defined]
        if hasattr(_g, 'm_cardinality_guard_new_groups_total'):
            g = _g.m_cardinality_guard_new_groups_total()
            if g: g.set(len(new_groups))  # type: ignore[attr-defined]
        if hasattr(_g, 'm_cardinality_guard_last_run_epoch'):
            import time as _t
            g = _g.m_cardinality_guard_last_run_epoch()
            if g: g.set(int(_t.time()))  # type: ignore[attr-defined]
        if hasattr(_g, 'm_cardinality_guard_allowed_growth_percent'):
            g = _g.m_cardinality_guard_allowed_growth_percent()
            if g: g.set(allow_pct)  # type: ignore[attr-defined]
        # Per-group growth percent (only for offenders)
        if hasattr(_g, 'm_cardinality_guard_growth_percent_labels'):
            for off in offenders:
                gp = off.get('growth_percent')
                grp = off.get('group')
                if gp is None or grp is None:
                    continue
                met = _g.m_cardinality_guard_growth_percent_labels(grp)
                if met:
                    try: met.set(gp)  # type: ignore[attr-defined]
                    except Exception: pass
    except Exception:
        pass
    return summary


#############################################
# Lightweight runtime registration guard
#############################################

import threading
import time  # placed late to avoid impacting existing import cost

try:  # optional in some test paths
    from prometheus_client import Counter as _GC_Counter  # type: ignore
    from prometheus_client import Gauge as _GC_Gauge
    from prometheus_client import Histogram as _GC_Histogram
except Exception:  # pragma: no cover
    _GC_Counter = _GC_Gauge = _GC_Histogram = None  # type: ignore

_rg_lock = threading.RLock()
_rg_metrics: dict[str, object] = {}
_rg_seen: dict[str, set[tuple[str,...]]] = {}
_rg_budget: dict[str, int] = {}
_rg_last_log: dict[tuple[str,str], float] = {}
_RG_SUPPRESS = 60.0

def _rg_rate_limited(key: tuple[str,str], msg: str):  # pragma: no cover - timing based
    now = time.time()
    last = _rg_last_log.get(key, 0.0)
    if now - last > _RG_SUPPRESS:
        _rg_last_log[key] = now
        logger.warning(msg)

class _RegistryGuard:
    def _register(self, kind: str, name: str, help_text: str, labels: list[str], budget: int, buckets=None):
        with _rg_lock:
            if name in _rg_metrics:
                # Duplicate registration attempt – increment duplicates counter if available
                try:
                    from src.metrics.generated import m_metric_duplicates_total_labels  # type: ignore
                    c = m_metric_duplicates_total_labels(name)
                    if c:
                        c.inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
                # Optional hard failure for CI / strict environments
                try:
                    import os
                    if os.getenv('G6_METRICS_FAIL_ON_DUP'):
                        raise RuntimeError(f"duplicate metric registration detected name={name}")
                except RuntimeError:
                    raise
                except Exception:
                    pass
                return _rg_metrics[name]
            try:
                if _GC_Counter is None or _GC_Gauge is None or _GC_Histogram is None:
                    # prometheus_client not installed in this runtime path; skip registration silently
                    return None
                if kind == 'counter':
                    metric = _GC_Counter(name, help_text, labels) if labels else _GC_Counter(name, help_text)
                elif kind == 'gauge':
                    metric = _GC_Gauge(name, help_text, labels) if labels else _GC_Gauge(name, help_text)
                elif kind == 'histogram':
                    if buckets is not None:
                        metric = _GC_Histogram(name, help_text, labels, buckets=buckets) if labels else _GC_Histogram(name, help_text, buckets=buckets)
                    else:
                        metric = _GC_Histogram(name, help_text, labels) if labels else _GC_Histogram(name, help_text)
                else:
                    raise ValueError(f"unknown metric kind {kind}")
                _rg_metrics[name] = metric
                _rg_seen[name] = set()
                _rg_budget[name] = budget
                return metric
            except Exception as e:  # pragma: no cover
                try:
                    import os
                    if os.getenv('G6_SUPPRESS_METRIC_DUP_WARN','').lower() in ('1','true','yes','on'):
                        # Silent suppression path (still allow fail-on-dup earlier to raise if configured)
                        return None
                except Exception:
                    pass
                _rg_rate_limited((name,'register'), f"metric.register.failed name={name} err={e}")
                return None

    def counter(self, name: str, help_text: str, labels: list[str], budget: int):
        return self._register('counter', name, help_text, labels, budget)
    def gauge(self, name: str, help_text: str, labels: list[str], budget: int):
        return self._register('gauge', name, help_text, labels, budget)
    def histogram(self, name: str, help_text: str, labels: list[str], budget: int, buckets=None):
        return self._register('histogram', name, help_text, labels, budget, buckets=buckets)

    def track(self, name: str, label_values: tuple[str,...]) -> bool:
        try:
            seen = _rg_seen.get(name)
            if seen is None:
                return True
            if label_values in seen:
                return True
            if len(seen) >= _rg_budget.get(name, 10_000):
                _rg_rate_limited((name,'budget'), f"metric.cardinality.exceeded name={name} budget={_rg_budget.get(name)} attempted={label_values}")
                return False
            seen.add(label_values)
            # Update per-metric series count gauge if available
            try:
                from src.metrics.generated import m_cardinality_series_total_labels  # type: ignore
                g = m_cardinality_series_total_labels(name)
                if g:
                    g.set(len(seen))  # type: ignore[attr-defined]
            except Exception:
                pass
            return True
        except Exception:
            return False

registry_guard = _RegistryGuard()

__all__ = ["check_cardinality", "registry_guard"]
