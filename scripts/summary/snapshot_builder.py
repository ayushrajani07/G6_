"""V2 Snapshot Builder (Phase 1 Base) -- PH1-02

Constructs a coherent frame from existing runtime sources (status + optional
panel JSON) under feature flag G6_SUMMARY_AGG_V2. This initial version avoids
any scoring, anomaly detection, or issue prioritization – it focuses solely on
producing a stable, single-pass consolidated data structure consumed by future
panels.

Design Objectives (Phase 1):
- Single pass IO (status + panels JSON if enabled) with defensive error handling.
- Normalize minimal subset: cycle, indices summary, alerts (shallow), memory stats.
- Provide typed dataclass `FrameSnapshotBase` for downstream evolution.
- Export build time metric counter placeholder (histogram added PH1-03).
- Avoid heavy dependencies (Rich not imported here).

Future Phases: scoring (Phase 2), issues (Phase 3), adaptive integration (Phase 4).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from prometheus_client import REGISTRY as _PROM_REGISTRY  # type: ignore
from prometheus_client import Counter as _PROM_Counter
from prometheus_client import Histogram as _PROM_Histogram  # type: ignore

from scripts.summary.thresholds import T

_get_metrics = None  # platform registry integration disabled for simplicity

FLAG = os.getenv("G6_SUMMARY_AGG_V2", "0").lower() in {"1","true","yes","on"}
# Optional signature v2 flag (defaults ON when aggregation flag on unless explicitly disabled)
SIG_FLAG = os.getenv("G6_SUMMARY_SIG_V2", "auto").lower()
if SIG_FLAG == "auto":
    SIG_FLAG = "on" if FLAG else "off"
SIG_FLAG_ACTIVE = SIG_FLAG in {"1","true","yes","on"}
DEBUG_LOG = os.getenv("G6_SUMMARY_V2_LOG_DEBUG", "0").lower() in {"1","true","yes","on"}

def _dbg(msg: str) -> None:  # lightweight conditional debug
    if DEBUG_LOG:
        logging.debug(f"[snapshot_builder] {msg}")

@dataclass
class CycleInfo:
    cycle: int | None = None
    last_duration_s: float | None = None
    interval_s: float | None = None

@dataclass
class IndexSummary:
    name: str
    dq_percent: float | None = None
    status: str | None = None
    age_s: float | None = None

@dataclass
class AlertsSummary:
    total: int = 0
    levels: dict[str,int] = field(default_factory=dict)

@dataclass
class MemorySummary:
    rss_mb: float | None = None
    tier: int | None = None  # naive threshold based tiering

@dataclass
class FrameSnapshotBase:
    ts: str
    cycle: CycleInfo
    indices: list[IndexSummary]
    alerts: AlertsSummary
    memory: MemorySummary
    raw_status_present: bool
    panels_mode: bool

# Simple metric counter (placeholder) – replaced/augmented later with histogram
_build_counter = 0
_metrics_initialized = False
_snapshot_hist: _PROM_Histogram | None = None
_snapshot_counter: _PROM_Counter | None = None
_alerts_dedup_counter: _PROM_Counter | None = None  # PH1-04
_refresh_skipped_counter: _PROM_Counter | None = None  # PH1-05

def _ensure_metrics() -> None:
    """Idempotently register snapshot metrics when aggregation flag is enabled.

    Uses a dynamic flag check each call so tests (or runtime) can enable
    G6_SUMMARY_AGG_V2 after initial import without requiring a hard module reload.
    """
    global _metrics_initialized, _snapshot_hist, _snapshot_counter, _alerts_dedup_counter, _refresh_skipped_counter
    if _metrics_initialized:
        return
    # Re-evaluate flag dynamically (do not rely solely on module import time)
    # Respect feature flag again (option B): only register metrics when aggregation flag is on.
    dyn_flag = os.getenv("G6_SUMMARY_AGG_V2", "0").lower() in {"1","true","yes","on"}
    if not dyn_flag:
        return
    # Register (or reuse) metrics directly on the global registry (flag ensured active).
    try:
        # Access internal mapping to reuse existing collectors if already defined
        name_map = getattr(_PROM_REGISTRY, '_names_to_collectors', {})  # type: ignore[attr-defined]
        if 'g6_summary_snapshot_build_seconds' in name_map:
            _snapshot_hist = name_map['g6_summary_snapshot_build_seconds']  # type: ignore[index]
        else:
            _snapshot_hist = _PROM_Histogram(
                'g6_summary_snapshot_build_seconds',
                'Snapshot builder wall time (seconds)',
                buckets=[
                    0.001, 0.002, 0.005, 0.01, 0.02,
                    0.05, 0.075, 0.1, 0.25, 0.5,
                    1, 2, 3,
                ],
            )
        # Counter naming: use base name without trailing _total (prom client appends)
        if 'g6_summary_v2_frames' in name_map:
            _snapshot_counter = name_map['g6_summary_v2_frames']  # type: ignore[index]
        else:
            _snapshot_counter = _PROM_Counter('g6_summary_v2_frames', 'Number of v2 summary frame snapshots built')
        if 'g6_summary_alerts_dedup_total' in name_map:
            _alerts_dedup_counter = name_map['g6_summary_alerts_dedup_total']  # type: ignore[index]
        else:
            _alerts_dedup_counter = _PROM_Counter('g6_summary_alerts_dedup_total', 'Alerts duplicates skipped (PH1-04)')
        # PH1-05: render refresh skip counter (registered only when signature flag active)
        if SIG_FLAG_ACTIVE:
            if 'g6_summary_refresh_skipped_total' in name_map:
                _refresh_skipped_counter = name_map['g6_summary_refresh_skipped_total']  # type: ignore[index]
            else:
                _refresh_skipped_counter = _PROM_Counter(
                    'g6_summary_refresh_skipped_total',
                    'Summary render refresh operations skipped due to unchanged signature (PH1-05)',
                )
        _metrics_initialized = True
    except Exception:  # pragma: no cover
        _snapshot_hist = None
        _snapshot_counter = None

class SnapshotBuildError(Exception):
    pass

def _read_json(path: str) -> Any:
    """Read JSON with mtime cache when available, fallback to direct read.

    Returns None on errors to match previous semantics in this module.
    """
    try:
        from pathlib import Path as _Path

        from src.utils.csv_cache import read_json_cached as _read_json_cached
    except Exception:
        _read_json_cached = None  # type: ignore
        _Path = None  # type: ignore
    try:
        if _read_json_cached is not None and _Path is not None:
            data = _read_json_cached(_Path(path))
            return data
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except Exception as e:
        logging.warning(f"[snapshot_builder] Failed reading {path}: {e}")
        return None

def _derive_cycle(status: dict[str, Any] | None) -> CycleInfo:
    if not status or not isinstance(status, dict):
        return CycleInfo()
    loop = status.get("loop") or {}
    if not isinstance(loop, dict):
        loop = {}
    return CycleInfo(
        cycle=loop.get("cycle"),
        last_duration_s=loop.get("last_duration"),
        interval_s=status.get("interval"),
    )

def _collect_indices(status: dict[str, Any] | None, panels_dir: str | None) -> list[IndexSummary]:
    result: list[IndexSummary] = []
    seen = set()
    # Prefer indices_detail from status
    if isinstance(status, dict) and isinstance(status.get("indices_detail"), dict):
        for name, data in status["indices_detail"].items():
            if not isinstance(data, dict):
                continue
            dq = None
            try:
                dq_obj = data.get("dq")
                if isinstance(dq_obj, dict):
                    dq = dq_obj.get("score_percent")
            except Exception:
                pass
            age = data.get("age") or data.get("age_sec")
            result.append(
                IndexSummary(
                    name=name,
                    dq_percent=dq,
                    status=str(data.get("status") or "") or None,
                    age_s=age,
                )
            )
            seen.add(str(name))
    # Optionally enrich from panels stream (latest items) to fill gaps
    if panels_dir:
        stream = _read_json(os.path.join(panels_dir, "indices_stream.json"))
        items: list[dict[str, Any]] = []
        if isinstance(stream, list):
            items = stream
        elif isinstance(stream, dict) and isinstance(stream.get("items"), list):
            items = stream.get("items")  # type: ignore
        # Keep most recent occurrence per index
        latest: dict[str, dict[str, Any]] = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            idx = str(it.get("index") or it.get("idx") or "").strip()
            if not idx:
                continue
            prev = latest.get(idx)
            t = it.get("time") or it.get("ts")
            if prev is None:
                latest[idx] = it
            else:
                # naive timestamp comparison lexical ok for iso8601
                if str(t) > str(prev.get("time") or prev.get("ts") or ""):
                    latest[idx] = it
        for idx, it in latest.items():
            if idx in seen:
                continue
            dq = it.get("dq_score") if isinstance(it.get("dq_score"), (int,float)) else None
            result.append(IndexSummary(name=idx, dq_percent=dq, status=str(it.get("status") or "") or None, age_s=None))
            seen.add(idx)
    return result

def _hash_alert(a: dict[str, Any]) -> str:
    try:
        # Normalize essential fields for dedupe key; fallback to repr
        t = str(a.get("time") or a.get("timestamp") or "")[:19]  # second resolution
        lvl = str(a.get("level") or a.get("severity") or "").upper()
        comp = str(a.get("component") or a.get("source") or "")
        msg = str(a.get("message") or "")
        raw = f"{t}|{lvl}|{comp}|{msg}".encode("utf-8", errors="ignore")
        return hashlib.sha1(raw).hexdigest()
    except Exception:
        return hashlib.sha1(repr(a).encode("utf-8", errors="ignore")).hexdigest()

def _generate_synthetic_alerts(status: dict[str, Any] | None) -> list[dict[str, Any]]:
    syn: list[dict[str, Any]] = []
    if not status or not isinstance(status, dict):
        return syn
    now_iso = datetime.now(UTC).isoformat()
    # Data quality heuristic (simple copy from panel logic subset)
    try:
        ids = status.get("indices_detail")
        if isinstance(ids, dict):
            low: list[str] = []
            for k, v in ids.items():
                if not isinstance(v, dict):
                    continue
                dq = v.get("dq")
                if isinstance(dq, dict):
                    sc = dq.get("score_percent")
                    if isinstance(sc, (int,float)) and sc == sc and sc < 80:  # not NaN and below threshold
                        low.append(f"{k}:{sc:.1f}%")
            if low:
                syn.append({
                    "time": now_iso,
                    "level": "WARNING" if all(":7" not in it and ":6" not in it for it in low) else "ERROR",
                    "component": "Data Quality",
                    "message": (
                        f"Low data quality: {', '.join(low[:3])}"
                        f"{' (+'+str(len(low)-3)+' more)' if len(low)>3 else ''}"
                    ),
                    "source": "synthetic",
                })
    except Exception:
        pass
    try:
        mk = status.get("market")
        if isinstance(mk, dict) and mk.get("status") == "CLOSED":
            syn.append({
                "time": now_iso,
                "level": "INFO",
                "component": "Market",
                "message": "Market is closed",
                "source": "synthetic"
            })
    except Exception:
        pass
    return syn

def _load_rolling_alerts_log(log_path: str) -> list[dict[str, Any]]:
    try:
        with open(log_path, encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("alerts"), list):
                return [a for a in data["alerts"] if isinstance(a, dict)]
    except FileNotFoundError:
        return []
    except Exception:
        return []
    return []

def _write_rolling_alerts_log(
    log_path: str,
    alerts: list[dict[str, Any]],
    *,
    max_entries: int = 500,
) -> None:  # pragma: no cover (IO best effort)
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        trimmed = alerts[-max_entries:]
        payload = {"updated_at": datetime.now(UTC).isoformat(), "alerts": trimmed}
        # Always write atomically to avoid interleaved data corruption (observed JSON extra data issue)
        try:
            from src.utils.output import atomic_write_json  # type: ignore
            atomic_write_json(log_path, payload, ensure_ascii=False, indent=2)
            # Post-write validation: ensure file is valid JSON; if not, rewrite once.
            try:
                with open(log_path, encoding='utf-8') as _vf:
                    _ = json.load(_vf)
            except Exception:
                # One retry on validation failure
                try:
                    atomic_write_json(log_path, payload, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            return
        except Exception:
            pass
        # Fallback manual atomic pattern
        try:
            import tempfile
            tmp_dir = os.path.dirname(log_path) or '.'
            fd, tmp_path = tempfile.mkstemp(prefix='._alerts_log.', dir=tmp_dir)
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                    json.dump(payload, fh, indent=2)
                    fh.flush()
                    os.fsync(fh.fileno()) if hasattr(os, 'fsync') else None
                os.replace(tmp_path, log_path)
            except Exception:
                try:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)
                except Exception:
                    pass
            # Validate after fallback write
            try:
                with open(log_path, encoding='utf-8') as _vf2:
                    _ = json.load(_vf2)
            except Exception:
                try:
                    with open(log_path, 'w', encoding='utf-8') as _fw2:
                        json.dump(payload, _fw2, indent=2)
                except Exception:
                    pass
        except Exception:
            # Final non-atomic fallback
            try:
                with open(log_path, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, indent=2)
            except Exception:
                pass
    except Exception:
        pass

def _collect_and_persist_alerts(status: dict[str, Any] | None, panels_dir: str | None) -> tuple[AlertsSummary, int]:
    """Collect alerts + synthetic + panels, persist rolling log once (PH1-04).

    Returns (AlertsSummary, duplicates_skipped).
    """
    # Strategy: maintain chronological ascending order so trimming keeps most recent tail.
    # Load existing rolling log first (assumed oldest->newest) then append freshly collected alerts.
    log_path = os.path.join("data", "panels", "alerts_log.json")
    alerts: list[dict[str, Any]] = _load_rolling_alerts_log(log_path)
    new_batch: list[dict[str, Any]] = []
    if isinstance(status, dict):  # status alerts/events
        for key in ("alerts", "events"):
            raw = status.get(key)
            if isinstance(raw, list):
                new_batch.extend([a for a in raw if isinstance(a, dict)])
    if panels_dir:  # panel file alerts
        pj = _read_json(os.path.join(panels_dir, "alerts.json"))
        if isinstance(pj, list):
            new_batch.extend([a for a in pj if isinstance(a, dict)])
    # Synthetic after real alerts
    new_batch.extend(_generate_synthetic_alerts(status))
    # Append new batch after historical alerts so they appear at end and survive tail trimming
    alerts.extend(new_batch)
    # Dedupe
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    duplicates = 0
    for a in alerts:
        h = _hash_alert(a)
        if h in seen:
            duplicates += 1
            continue
        seen.add(h)
        out.append(a)
    # Persist updated list (original + new synthetic) if flag active
    # Determine rolling log max entries (env override) with defensive parsing
    try:
        _max_env = os.getenv("G6_SUMMARY_ALERTS_LOG_MAX", "")
        if _max_env.strip():
            max_entries = int(_max_env)
            if max_entries <= 0:  # treat non-positive as disable trimming (keep default cap)
                max_entries = 500
        else:
            max_entries = 500
    except Exception:
        max_entries = 500
    _write_rolling_alerts_log(log_path, out, max_entries=max_entries)
    # Summarize levels
    total = 0
    levels: dict[str,int] = {}
    for a in out:
        lvl = str(a.get("level") or a.get("severity") or "").upper()
        if not lvl:
            continue
        total += 1
        levels[lvl] = levels.get(lvl,0)+1
    # Update counter metric
    if _alerts_dedup_counter is not None and duplicates:
        try:
            _alerts_dedup_counter.inc(duplicates)
        except Exception:
            pass
    return AlertsSummary(total=total, levels=levels), duplicates

def _collect_memory(status: dict[str, Any] | None) -> MemorySummary:
    if not status or not isinstance(status, dict):
        return MemorySummary()
    mem = status.get("memory")
    rss = None
    if isinstance(mem, dict):
        rss = mem.get("rss_mb") or mem.get("rss")
        try:
            if isinstance(rss, (int,float)) and rss > 10000:  # assume bytes perhaps
                rss = rss / (1024*1024)
        except Exception:
            pass
    tier = None
    try:
        if isinstance(rss, (int,float)):
            if rss >= T.mem_tier3_mb:
                tier = 3
            elif rss >= T.mem_tier2_mb:
                tier = 2
            else:
                tier = 1
    except Exception:
        pass
    return MemorySummary(rss_mb=rss, tier=tier)

def build_frame_snapshot(status: dict[str, Any] | None, *, panels_dir: str | None = None) -> FrameSnapshotBase:
    """Build a base snapshot (Phase 1) from current sources.

    This function is idempotent for a given input status + panel artifacts.
    Raises SnapshotBuildError only for truly irrecoverable conditions (rare in phase 1).
    """
    global _build_counter
    started = time.time()
    _ensure_metrics()
    try:
        cycle = _derive_cycle(status)
        _dbg(f"cycle derived: cycle={cycle.cycle} duration={cycle.last_duration_s} interval={cycle.interval_s}")
        indices = _collect_indices(status, panels_dir if panels_dir and os.path.isdir(panels_dir) else None)
        _dbg(f"indices collected: count={len(indices)} panels_mode={bool(panels_dir)}")
        if FLAG:  # relocated path
            alerts, _dedup = _collect_and_persist_alerts(
                status,
                panels_dir if panels_dir and os.path.isdir(panels_dir) else None,
            )
            _dbg(f"alerts aggregated (relocated): total={alerts.total} levels={alerts.levels}")
        else:
            alerts = _collect_alerts(status, panels_dir if panels_dir and os.path.isdir(panels_dir) else None)  # type: ignore
            _dbg(f"alerts aggregated (legacy): total={alerts.total} levels={alerts.levels}")
        memory = _collect_memory(status)
        _dbg(f"memory summary: rss_mb={memory.rss_mb} tier={memory.tier}")
        snap = FrameSnapshotBase(
            ts=datetime.now(UTC).isoformat(),
            cycle=cycle,
            indices=indices,
            alerts=alerts,
            memory=memory,
            raw_status_present=bool(status),
            panels_mode=bool(panels_dir),
        )
        _build_counter += 1
        # Metrics record
        if _snapshot_counter is not None:
            try:
                _snapshot_counter.inc()
            except Exception:
                pass
        return snap
    except Exception as e:
        logging.exception("[snapshot_builder] Unexpected build failure")
        raise SnapshotBuildError(str(e)) from e
    finally:
        # Placeholder hook for future histogram instrumentation (PH1-03)
        elapsed = time.time() - started
        if _snapshot_hist is not None:
            try:
                _snapshot_hist.observe(elapsed)
            except Exception:
                pass

def snapshot_to_dict(snap: FrameSnapshotBase) -> dict[str, Any]:
    return asdict(snap)

__all__ = [
    "FLAG",
    "FrameSnapshotBase",
    "build_frame_snapshot",
    "snapshot_to_dict",
    "SnapshotBuildError",
]

def _reset_metrics_for_tests() -> None:  # pragma: no cover - test utility
    global _metrics_initialized, _snapshot_hist, _snapshot_counter, _alerts_dedup_counter
    _metrics_initialized = False
    _snapshot_hist = None
    _snapshot_counter = None
    _alerts_dedup_counter = None

def _get_internal_metric_objects(
) -> tuple[_PROM_Counter | None, _PROM_Histogram | None]:  # pragma: no cover - diagnostic/testing helper
    return _snapshot_counter, _snapshot_hist

def _get_alerts_dedup_metric() -> _PROM_Counter | None:  # pragma: no cover - test helper
    return _alerts_dedup_counter

def _get_refresh_skipped_metric() -> _PROM_Counter | None:  # pragma: no cover - test helper
    return _refresh_skipped_counter

def compute_snapshot_signature(status: dict[str, Any] | None, *, panels_dir: str | None = None) -> str | None:
    """Compute a lightweight signature over snapshot-relevant stable fields.

    Excludes volatile timestamps. Inputs considered:
      - loop.cycle
      - indices list (names only)
      - total alerts count (after relocation logic if active) and level distribution
      - memory tier
    The signature is only produced when SIG_FLAG_ACTIVE is true to avoid overhead
    during phased rollout.
    """
    if not SIG_FLAG_ACTIVE:
        return None
    try:
        cycle = None
        if isinstance(status, dict):
            loop = status.get('loop') if isinstance(status.get('loop'), dict) else None
            if isinstance(loop, dict):
                c = loop.get('cycle') or loop.get('number')
                if isinstance(c, (int, float)):
                    cycle = int(c)
        # Indices list via existing helper (avoid full builder call); fallback to status indices
        indices: list[str] = []
        try:
            ids = status.get('indices_detail') if isinstance(status, dict) else None
            if isinstance(ids, dict):
                indices = sorted(str(k) for k in ids.keys())
            elif isinstance(status, dict):
                raw = status.get('indices') or status.get('symbols')
                if isinstance(raw, list):
                    indices = sorted(str(x) for x in raw)
        except Exception:
            indices = []
        # Alerts (persisted rolling log path); we reuse builder helpers for consistency
        alerts_summary = None
        if FLAG:
            try:
                # Combine rolling log + current status alerts/events (without synthetic generation)
                log_path = os.path.join('data', 'panels', 'alerts_log.json')
                combined: list[dict[str, Any]] = []
                combined.extend(_load_rolling_alerts_log(log_path))
                if isinstance(status, dict):
                    for key in ('alerts','events'):
                        raw = status.get(key)
                        if isinstance(raw, list):
                            combined.extend([a for a in raw if isinstance(a, dict)])
                total = 0
                levels: dict[str,int] = {}
                for a in combined:
                    lvl = str(a.get('level') or a.get('severity') or '').upper()
                    if not lvl:
                        continue
                    total += 1
                    levels[lvl] = levels.get(lvl,0)+1
                alerts_summary = (total, tuple(sorted(levels.items())))
            except Exception:
                alerts_summary = None
        # Memory tier
        mem_tier = None
        try:
            mem = status.get('memory') if isinstance(status, dict) else None
            if isinstance(mem, dict):
                rss = mem.get('rss_mb') or mem.get('rss')
                if isinstance(rss, (int, float)):
                    if rss >= T.mem_tier3_mb:
                        mem_tier = 3
                    elif rss >= T.mem_tier2_mb:
                        mem_tier = 2
                    else:
                        mem_tier = 1
        except Exception:
            mem_tier = None
        base = json.dumps({
            'c': cycle,
            'i': indices,
            'a': alerts_summary,
            'm': mem_tier,
        }, sort_keys=True, separators=(',',':')).encode('utf-8')
        return hashlib.sha1(base).hexdigest()
    except Exception:
        return None

# Backwards compatibility: legacy function kept until PH1-04 fully merged
def _collect_alerts(
    status: dict[str, Any] | None,
    panels_dir: str | None,
) -> AlertsSummary:  # pragma: no cover - legacy path
    # Use simplified legacy logic (copied from prior implementation) for when FLAG is off
    alerts: list[dict[str, Any]] = []
    if status:
        raw_alerts = status.get("alerts")
        if isinstance(raw_alerts, list):
            alerts.extend([a for a in raw_alerts if isinstance(a, dict)])
    if panels_dir:
        pj = _read_json(os.path.join(panels_dir, "alerts.json"))
        if isinstance(pj, list):
            alerts.extend([a for a in pj if isinstance(a, dict)])
    total = 0
    levels: dict[str,int] = {}
    for a in alerts:
        lvl = str(a.get("level") or a.get("severity") or "").upper()
        if not lvl:
            continue
        total += 1
        levels[lvl] = levels.get(lvl,0)+1
    return AlertsSummary(total=total, levels=levels)
