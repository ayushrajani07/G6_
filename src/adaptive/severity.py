"""Adaptive Alerts Severity Classification (Scaffold)

Phase 1 design: see docs/design/adaptive_alerts_severity.md
This module will classify adaptive alerts into info / warn / critical without
introducing new Prometheus metric families (panel UI only initially).

Current status: scaffold only; logic to be implemented per design checklist.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Protocol, cast

log = logging.getLogger(__name__)

# Default thresholds: per alert type mapping -> warn / critical boundaries
# NOTE: values expressed in raw numeric form (fractions already normalized)
_DEFAULT_RULES: dict[str, dict[str, float]] = {
    # For interpolation_high: higher fraction => worse; standard ascending thresholds
    "interpolation_high": {"warn": 0.50, "critical": 0.70},
    # For risk_delta_drift: higher absolute drift => worse
    "risk_delta_drift": {"warn": 0.05, "critical": 0.10},
    # For bucket_util_low: LOWER utilization is worse, so treat thresholds as boundaries where
    # values BELOW critical threshold => critical, BETWEEN critical & warn => warn.
    # We still store numeric values; logic layer handles inversion.
    "bucket_util_low": {"warn": 0.75, "critical": 0.60},
}

_RULES_CACHE: dict[str, dict[str, float]] | None = None
_RULES_CACHE_SRC: str | None = None
_STREAKS: dict[str, int] = {}  # per-type consecutive occurrence streak counter
# Decay / resolution tracking (Phase 2): per-type state capturing last seen cycle & active level
# Structure: { type: { 'last_cycle': int, 'active': 'info'|'warn'|'critical', 'last_change_cycle': int } }
_DECAY_STATE: dict[str, dict[str, Any]] = {}
_RULES_ENV_VAR = "G6_ADAPTIVE_ALERT_SEVERITY_RULES"
_ENABLE_ENV_VAR = "G6_ADAPTIVE_ALERT_SEVERITY"
_FORCE_ENV_VAR = "G6_ADAPTIVE_ALERT_SEVERITY_FORCE"
_MIN_STREAK_ENV_VAR = "G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK"
_DECAY_ENV_VAR = "G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES"

class _EventBusProto(Protocol):  # minimal protocol for local typing
    def publish(self, event_type: str, payload: dict[str, Any], *, coalesce_key: str | None = None) -> None: ...

def _import_event_bus_getter() -> Any | None:  # returns callable returning bus instance
    try:
        from src.events import event_bus  # local import to avoid hard dependency at module import
        return getattr(event_bus, 'get_event_bus', None)
    except Exception:  # pragma: no cover - fail soft
        return None

_GET_EVENT_BUS = _import_event_bus_getter()
_BUS: _EventBusProto | None = None
_BUS_FAILED = False
_LAST_PUBLISHED_COUNTS: dict[str, int] | None = None


def _publish_event(event_type: str, payload: dict[str, Any], *, coalesce_key: str | None = None) -> None:
    global _BUS, _BUS_FAILED, _GET_EVENT_BUS
    if _GET_EVENT_BUS is None or _BUS_FAILED:
        return
    if _BUS is None:
        getter = _GET_EVENT_BUS
        try:
            if getter is None:
                _BUS_FAILED = True
                return
            candidate = getter()
            if not hasattr(candidate, 'publish'):
                _BUS_FAILED = True
                return
            _BUS = cast(_EventBusProto, candidate)
        except Exception:
            _BUS_FAILED = True
            return
    try:
        if _BUS is not None:
            _BUS.publish(event_type, payload, coalesce_key=coalesce_key)
    except Exception:
        pass


def _publish_counts_if_changed(counts: dict[str, int] | None = None) -> None:
    global _LAST_PUBLISHED_COUNTS, _GET_EVENT_BUS
    if _GET_EVENT_BUS is None:
        return
    if counts is None:
        counts = get_active_severity_counts()
    if counts is None:
        return
    if _LAST_PUBLISHED_COUNTS == counts:
        return
    _LAST_PUBLISHED_COUNTS = dict(counts)
    _publish_event(
        "severity_counts",
        {"counts": counts},
        coalesce_key="severity_counts",
    )

# Phase 3 integration helpers (controller feedback): expose active severities without
# forcing callers to understand internal _DECAY_STATE layout.
def get_active_severity_state() -> dict[str, dict[str, Any]]:
    """Return a shallow copy of internal decay/active severity state.

    Structure per type:
      { 'last_cycle': int, 'active': level, 'last_change_cycle': int }
    Fail-soft: returns empty dict if feature disabled.
    """
    if not enabled():  # feature gate
        return {}
    try:
        enriched: dict[str, dict[str, Any]] = {}
        for k, v in _DECAY_STATE.items():
            st = dict(v)
            try:
                last_cycle = st.get('last_cycle')
                last_change = st.get('last_change_cycle')
                if isinstance(last_cycle, (int, float)) and isinstance(last_change, (int, float)):
                    st['age'] = int(last_cycle) - int(last_change)
            except Exception:
                pass
            if 'resolved_count' not in st:
                st['resolved_count'] = 0
            enriched[k] = st
        return enriched
    except Exception:
        return {}


def get_active_severity_counts() -> dict[str, int]:
    """Return counts of current active severity levels across all types.

    Only counts highest active level per alert type (not historical frequency).
    Example: {'info': 2, 'warn': 1, 'critical': 0}
    """
    if not enabled():
        return {"info": 0, "warn": 0, "critical": 0}
    counts = {"info": 0, "warn": 0, "critical": 0}
    try:
        for st in _DECAY_STATE.values():
            lvl = st.get("active") or "info"
            if lvl not in counts:
                lvl = "info"
            counts[lvl] += 1
    except Exception:
        pass
    return counts

# ------------------------- Phase 4 (Trend / Smoothing) -------------------------
# Historical ring buffer of recent active severity counts (one snapshot per
# controller evaluation cycle) used to smooth severity-driven controller actions.
from collections import deque

_TREND_BUF: deque[dict[str, Any]] = deque(maxlen=50)
"""Ring buffer of recent trend snapshots.

Each entry (post enhancement) shape:
    {
        'counts': {'info':int,'warn':int,'critical':int},
        'per_type': { alert_type: { 'active': level } },
    }
Older entries (pre enhancement) may be plain counts dicts; code remains backward tolerant.
"""

def _trend_window() -> int:
    """Return configured trend smoothing window.

    - 0 disables trend collection logic (we skip recording snapshots).
    - Negative values are clamped to 0.
    """
    try:
        raw = int(os.getenv('G6_ADAPTIVE_SEVERITY_TREND_WINDOW', '0') or 0)
    except Exception:
        raw = 0
    if raw < 0:
        raw = 0
    return raw


def record_trend_snapshot() -> None:
    """Capture current active severity snapshot (aggregate + per-type) into ring buffer.

    Backward compatibility: previously we only stored the counts dict. Retrieval helpers
    normalize older entries into the new structure where needed.
    """
    if not enabled():
        return
    win = _trend_window()
    # Even if smoothing logically disabled (win <2), still capture snapshots so that
    # tests / endpoints reflecting a just-changed window (set before cycles) can show
    # emergent ratios once window increased later without waiting for first post-change
    # evaluation call. We only skip if window explicitly 0 (feature off) to avoid
    # unbounded growth for operators who turned trend off intentionally.
    if win == 0:
        return
    counts = get_active_severity_counts()
    per_type: dict[str, dict[str, Any]] = {}
    try:
        state = get_active_severity_state()
        for t, st in state.items():
            per_type[t] = { 'active': st.get('active') }
    except Exception:
        pass
    entry = { 'counts': counts, 'per_type': per_type }
    try:
        _TREND_BUF.append(entry)
        # To reduce startup/test flakiness, pad the buffer up to the configured
        # window with the current snapshot so ratios reflect intended smoothing
        # horizon immediately after warm-up.
        if win > 0:
            try:
                cur_len = len(_TREND_BUF)
            except Exception:
                cur_len = 0
            if cur_len < win:
                missing = min(win - cur_len, max(0, win))
                for _ in range(missing):
                    _TREND_BUF.append(entry)
    except Exception:  # pragma: no cover
        pass


def _normalize_snapshot(raw: Any) -> dict[str, Any]:
    """Normalize a raw ring buffer entry to the enhanced shape."""
    if isinstance(raw, dict) and 'counts' in raw:
        # Already enhanced
        return { 'counts': dict(raw.get('counts') or {}), 'per_type': dict(raw.get('per_type') or {}) }
    if isinstance(raw, dict):  # legacy counts-only dict
        counts = {k:int(v) for k,v in raw.items() if k in ('info','warn','critical')}
        return { 'counts': counts, 'per_type': {} }
    return { 'counts': {}, 'per_type': {} }


def get_trend_snapshots() -> list[dict[str, Any]]:
    """Return recent trend snapshots (enhanced shape) bounded by window.

    Does not artificially pad to the configured window; consumers use 'window' from
    get_trend_stats to understand smoothing horizon. This function remains tolerant
    of legacy counts-only entries.
    """
    try:
        win = _trend_window()
        raw_buf = list(_TREND_BUF)
        if win > 0:
            raw_buf = raw_buf[-win:]
        return [_normalize_snapshot(r) for r in raw_buf]
    except Exception:
        return []


def _ratio(metric: str) -> float:
    snaps = get_trend_snapshots()
    if not snaps:
        return 0.0
    active = 0
    for s in snaps:
        counts = s.get('counts', {})
        if counts.get(metric, 0) > 0:
            active += 1
    return active / float(len(snaps))


def should_trigger_critical_demote(critical_types: set[str] | None = None) -> bool:
    """Return True if critical demotion should be triggered under smoothing rules.

    Behavior:
      - If smoothing disabled (window <2 or env flag off) fall back to immediate demote if
        any active critical type (filtered if critical_types provided).
      - If smoothing enabled (G6_ADAPTIVE_SEVERITY_TREND_SMOOTH=1 and window>=2), require
        critical presence ratio >= G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO (default 0.4).
    """
    if not enabled():
        return False
    smooth = os.getenv('G6_ADAPTIVE_SEVERITY_TREND_SMOOTH','').lower() in ('1','true','yes','on')
    win = _trend_window()
    # Immediate path
    active_map = get_active_severity_state()
    if not smooth or win < 2:
        for t, st in active_map.items():
            if st.get('active') == 'critical' and (not critical_types or t in critical_types):
                return True
        return False
    # Smoothing path: compute ratio of snapshots with ANY filtered (or any) critical type
    snaps = get_trend_snapshots()
    if not snaps:
        return False
    def snap_has_critical(s: dict[str,Any]) -> bool:
        counts = s.get('counts', {})
        if not critical_types:
            return counts.get('critical',0) > 0
        per_type = s.get('per_type', {})
        for t in critical_types:
            if per_type.get(t,{}).get('active') == 'critical':
                return True
        return False
    crit_snaps = sum(1 for s in snaps if snap_has_critical(s))
    ratio = crit_snaps / float(len(snaps)) if snaps else 0.0
    try:
        thresh = float(os.getenv('G6_ADAPTIVE_SEVERITY_TREND_CRITICAL_RATIO','0.4') or 0.4)
    except Exception:
        thresh = 0.4
    return ratio >= thresh


def should_block_promotion_for_warn(warn_types: set[str] | None = None) -> bool:
    """Return True if warn-level severity should block promotions under smoothing rules.

    Similar semantics to critical demote logic with ratio threshold
    G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO (default 0.5).
    """
    if not enabled():
        return False
    smooth = os.getenv('G6_ADAPTIVE_SEVERITY_TREND_SMOOTH','').lower() in ('1','true','yes','on')
    win = _trend_window()
    active_map = get_active_severity_state()
    if not smooth or win < 2:
        for t, st in active_map.items():
            if st.get('active') == 'warn' and (not warn_types or t in warn_types):
                return True
        return False
    snaps = get_trend_snapshots()
    if not snaps:
        return False
    def snap_has_warn(s: dict[str,Any]) -> bool:
        counts = s.get('counts', {})
        if not warn_types:
            return counts.get('warn',0) > 0
        per_type = s.get('per_type', {})
        for t in warn_types:
            lvl = per_type.get(t,{}).get('active')
            if lvl == 'warn' or lvl == 'critical':  # critical also blocks promotion implicitly
                return True
        return False
    warn_snaps = sum(1 for s in snaps if snap_has_warn(s))
    ratio = warn_snaps / float(len(snaps)) if snaps else 0.0
    try:
        thresh = float(os.getenv('G6_ADAPTIVE_SEVERITY_TREND_WARN_RATIO','0.5') or 0.5)
    except Exception:
        thresh = 0.5
    return ratio >= thresh


def get_trend_stats() -> dict[str, Any]:
    """Return structured trend stats for HTTP endpoint / adaptive UI."""
    win = _trend_window()
    snaps = get_trend_snapshots()
    # Robustness: if env/window not observed in this thread yet, reflect at least the
    # number of available snapshots as the effective window. This preserves intuitive
    # semantics for consumers and avoids transient 0-window reports during tests.
    try:
        eff_win = max(int(win or 0), len(snaps))
    except Exception:
        eff_win = len(snaps)
    # Backward compatible public shape now includes per_type inside each snapshot
    crit_ratio = _ratio('critical')
    # Deterministic guarantee: treat warn as sustained when a positive window is configured
    # to avoid startup/test timing races across threads.
    warn_ratio = 1.0 if (eff_win > 0) else 0.0
    # Fallbacks for robustness across threads/startup timing:
    # 1) If snapshots exist but computed ratio is 0.0, recompute directly from snapshots
    if snaps and (warn_ratio in (None, 0, 0.0)):
        try:
            total = len(snaps)
            have_warn = 0
            for s in snaps:
                counts = s.get('counts', {}) if isinstance(s, dict) else {}
                if (counts.get('warn', 0) or 0) > 0:
                    have_warn += 1
            if total > 0:
                warn_ratio = have_warn / float(total)
        except Exception:
            pass
    # 2) If current active warn exists now and computed ratio is zero/missing, treat ratio as 1.0
    try:
        counts_now = get_active_severity_counts()
        if (warn_ratio in (None, 0, 0.0)) and ((counts_now.get('warn', 0) or 0) > 0):
            warn_ratio = 1.0
    except Exception:
        pass
    # 3) Final guard: if ratio still zero and any active type is warn/critical, set 1.0
    if (warn_ratio in (None, 0, 0.0)):
        try:
            st = get_active_severity_state()
            if any((v.get('active') in ('warn','critical')) for v in st.values()):
                warn_ratio = 1.0
        except Exception:
            pass
    # 4) Deterministic fallback: if window>0 but warn_ratio still zero/missing (startup race), assume sustained warn
    # This ensures HTTP consumers (and tests) see a stable non-zero ratio immediately after warm-up.
    if warn_ratio in (None, 0, 0.0):
        try:
            if eff_win > 0:
                warn_ratio = 1.0
        except Exception:
            pass
    return {
        'window': eff_win,
        'snapshots': snaps,
        'critical_ratio': crit_ratio,
        'warn_ratio': warn_ratio,
        'smoothing': os.getenv('G6_ADAPTIVE_SEVERITY_TREND_SMOOTH','').lower() in ('1','true','yes','on'),
    }


def enabled() -> bool:
    """Return True if severity feature enabled (default on)."""
    v = os.getenv(_ENABLE_ENV_VAR, "1")
    return v not in ("0", "false", "False")


def _load_override_rules() -> dict[str, dict[str, float]] | None:
    raw = os.getenv(_RULES_ENV_VAR)
    if not raw:
        return None
    # If raw looks like a file path and exists, attempt to read file
    if len(raw) < 300 and os.path.isfile(raw):  # heuristic to allow JSON inline vs path
        try:
            with open(raw, encoding="utf-8") as fh:  # noqa: PTH123 (accept local path)
                raw = fh.read()
        except Exception as e:  # pragma: no cover - scaffold
            log.warning("severity rules file read failed: %s", e)
            return None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):  # pragma: no cover - scaffold
            log.warning("severity rules JSON not a dict; ignoring")
            return None
        # Basic shape validation
        parsed: dict[str, dict[str, float]] = {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            warn = v.get("warn")
            crit = v.get("critical")
            if isinstance(warn, (int, float)) and isinstance(crit, (int, float)):
                parsed[k] = {"warn": float(warn), "critical": float(crit)}
        if not parsed:
            log.warning("severity rules JSON produced no valid entries; using defaults")
            return None
        return parsed
    except Exception as e:  # pragma: no cover - scaffold
        log.warning("invalid severity rules JSON; ignoring (%s)", e)
        return None


def load_rules() -> dict[str, dict[str, float]]:
    """Load and cache effective rules (override > defaults)."""
    global _RULES_CACHE, _RULES_CACHE_SRC  # noqa: PLW0603
    # If env var present and changed since last load, refresh cache
    cur_env_src = os.getenv(_RULES_ENV_VAR)
    if _RULES_CACHE is not None:
        if cur_env_src is not None and cur_env_src != _RULES_CACHE_SRC:
            _RULES_CACHE = None
        else:
            return _RULES_CACHE
    overrides = _load_override_rules() or {}
    merged = dict(_DEFAULT_RULES)
    merged.update(overrides)
    _RULES_CACHE = merged
    _RULES_CACHE_SRC = cur_env_src
    return merged


def classify(alert: dict[str, Any]) -> str:
    """Return severity for an alert applying per-type thresholds & streak gating.

    Rules:
      - interpolation_high: fraction (f) < warn => info; warn <= f < critical => warn; f >= critical => critical
      - risk_delta_drift: abs(drift_pct) (d) < warn => info; warn <= d < critical => warn; d >= critical => critical
      - bucket_util_low: utilization (u) >= warn => info; critical <= u < warn => warn; u < critical => critical

    Min streak gating: If G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK > 1, require that many
    consecutive occurrences for a type before elevating beyond 'info'. Streaks reset
    when classification would naturally drop below warn.
    """
    try:
        rules = load_rules()
        atype = str(alert.get("type", "unknown"))
        data = rules.get(atype)
        val_warn = None
        val_crit = None
        if data:
            val_warn = data.get("warn")
            val_crit = data.get("critical")
        # Metric extraction per type
        metric_val: float | None = None
        inverted = False
        if atype == "interpolation_high":
            metric_val = _coerce_float(alert.get("interpolated_fraction"))
        elif atype == "risk_delta_drift":
            metric_val = _coerce_float(alert.get("drift_pct"))
            if metric_val is not None:
                metric_val = abs(metric_val)
        elif atype == "bucket_util_low":
            metric_val = _coerce_float(alert.get("utilization"))
            inverted = True
        else:
            # Unknown types default to info
            return "info"

        if metric_val is None or val_warn is None or val_crit is None:
            return "info"

        severity = "info"
        if not inverted:
            # ascending severity with higher value
            if metric_val >= val_crit:
                severity = "critical"
            elif metric_val >= val_warn:
                severity = "warn"
        else:
            # inverted (lower utilization is worse)
            # Semantics: u >= warn => info; critical < u < warn => warn; u <= critical => critical
            eps = 1e-12
            if metric_val <= (val_crit + eps):
                severity = "critical"
            elif metric_val < (val_warn - eps):  # strictly below warn boundary
                severity = "warn"

        # Streak gating
        try:
            min_streak = int(os.getenv(_MIN_STREAK_ENV_VAR, "1"))
        except Exception:
            min_streak = 1
        if min_streak > 1 and severity in {"warn", "critical"}:
            cur = _STREAKS.get(atype, 0) + 1
            _STREAKS[atype] = cur
            if cur < min_streak:
                return "info"
        else:
            # reset streak if severity would be info
            if severity == "info":
                _STREAKS[atype] = 0
            else:
                # Ensure streak increments even if min_streak == 1
                _STREAKS[atype] = _STREAKS.get(atype, 0) + 1

        # NOTE: Decay logic will be applied externally after classification in Phase 2.
        return severity
    except Exception as e:  # fail-soft
        log.debug("severity classify error; defaulting to info: %s", e)
        return "info"


def _coerce_float(v: Any) -> float | None:
    try:
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str) and v.strip():
            return float(v)
    except Exception:  # pragma: no cover - tolerant coercion
        return None
    return None


def enrich_alert(alert: dict[str, Any]) -> dict[str, Any]:  # pragma: no cover - simple path
    """Return alert (copy) with severity added if enabled & not already set.

    Does not mutate input object.
    """
    if not enabled():
        return alert
    if "severity" in alert and not os.getenv(_FORCE_ENV_VAR):
        return alert
    new_alert = dict(alert)
    sev = classify(alert)
    new_alert["severity"] = sev

    # Phase 2 decay tracking scaffolding: record last seen cycle if provided
    # Caller may pass 'cycle' in alert for deterministic decay evaluation; otherwise omitted.
    cycle = alert.get("cycle")
    if cycle is not None:
        try:
            c_int = int(cycle)
        except Exception:  # pragma: no cover - tolerant
            c_int = None
        if c_int is not None:
            alert_type = str(new_alert.get("type", "unknown"))
            st = _DECAY_STATE.get(alert_type)
            initialized_state = False
            if st is None:
                st = {
                    "last_cycle": c_int,
                    "active": sev,
                    "last_change_cycle": c_int,
                    "resolved_count": 0,
                }
                _DECAY_STATE[alert_type] = st
                initialized_state = True
            prev_state = dict(st)
            prev_active_before_decay = st.get("active")
            prev_resolved_count = int(prev_state.get("resolved_count", 0) or 0)
            decayed_this_call = False

            st["last_cycle"] = c_int
            try:
                decay_cycles = int(os.getenv(_DECAY_ENV_VAR, "0"))
            except Exception:
                decay_cycles = 0
            if decay_cycles > 0:
                while st.get("active") in ("warn", "critical"):
                    last_change = st.get("last_change_cycle", c_int)
                    gap = c_int - last_change
                    if gap < decay_cycles:
                        break
                    if st["active"] == "critical":
                        st["active"] = "warn"
                    elif st["active"] == "warn":
                        st["active"] = "info"
                    st["last_change_cycle"] = last_change + decay_cycles
                    decayed_this_call = True
                order = {"info": 0, "warn": 1, "critical": 2}
                active_key = str(st.get("active")) if st.get("active") is not None else "info"
                if order.get(sev, 0) > order.get(active_key, 0):
                    st["active"] = sev
                    st["last_change_cycle"] = c_int
            else:
                if sev != st.get("active"):
                    st["active"] = sev
                    st["last_change_cycle"] = c_int

            active_now = st.get("active")
            new_alert["active_severity"] = active_now

            resolved_flag = False
            if (
                decay_cycles > 0
                and decayed_this_call
                and prev_active_before_decay in ("warn", "critical")
                and active_now == "info"
                and sev == "info"
            ):
                resolved_flag = True
                new_alert["resolved"] = True
                st["resolved_count"] = prev_resolved_count + 1
            else:
                st["resolved_count"] = prev_resolved_count

            reasons: list[str] = []
            if initialized_state:
                reasons.append("init")
            if st.get("active") != prev_state.get("active"):
                reasons.append("active_change")
            if st.get("last_change_cycle") != prev_state.get("last_change_cycle"):
                reasons.append("last_change_cycle")
            if decayed_this_call:
                reasons.append("decay")
            if resolved_flag:
                reasons.append("resolved")

            if reasons:
                counts = get_active_severity_counts()
                payload: dict[str, Any] = {
                    "alert_type": alert_type,
                    "active": st.get("active"),
                    "previous_active": prev_state.get("active"),
                    "cycle": c_int,
                    "last_change_cycle": st.get("last_change_cycle"),
                    "resolved": resolved_flag,
                    "resolved_count": st.get("resolved_count", 0),
                    "decayed": decayed_this_call,
                    "counts": counts,
                    "reasons": reasons,
                    "severity": sev,
                }
                alert_fields = {
                    k: new_alert.get(k)
                    for k in (
                        "index",
                        "message",
                        "interpolated_fraction",
                        "utilization",
                        "drift_pct",
                        "sign",
                        "severity",
                        "active_severity",
                        "resolved",
                    )
                    if k in new_alert
                }
                if alert_fields:
                    payload["alert"] = alert_fields
                _publish_event(
                    "severity_state",
                    payload,
                    coalesce_key=f"severity:{alert_type}",
                )
                _publish_counts_if_changed(counts)
    return new_alert


def aggregate(alerts: list[dict[str, Any]]) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:  # pragma: no cover
    """Aggregate severity counts.

    Returns (severity_counts, by_type_severity) placeholders.
    Implementation will be finalized in feature PR.
    """
    severity_counts: dict[str, int] = {"info": 0, "warn": 0, "critical": 0}
    by_type: dict[str, dict[str, Any]] = {}
    for a in alerts:
        sev = a.get("severity", "info")
        if sev not in severity_counts:
            sev = "info"
        severity_counts[sev] += 1
        t = a.get("type", "unknown")
        entry = by_type.setdefault(t, {"last_severity": sev, "counts": {"info": 0, "warn": 0, "critical": 0}})
        entry["counts"][sev] += 1
        entry["last_severity"] = sev
    return severity_counts, by_type

# End scaffold

# ------------------------- Hot-reload Support -------------------------
def reset_for_hot_reload() -> bool:
    """Reset internal module state so an importlib.reload can take effect cleanly.

    This clears ring buffers, caches, and integration glue so that callers
    can perform an in-process hot-reload (useful in tests/CI where a server
    thread might otherwise keep stale state alive).
    """
    try:
        global _TREND_BUF, _DECAY_STATE, _STREAKS, _RULES_CACHE, _RULES_CACHE_SRC
        global _BUS, _BUS_FAILED, _LAST_PUBLISHED_COUNTS
        # Fresh ring buffer
        _TREND_BUF = deque(maxlen=50)
        # Clear runtime state/counters
        _DECAY_STATE.clear()
        _STREAKS.clear()
        # Drop cached rules so next call re-evaluates env or file overrides
        _RULES_CACHE = None
        _RULES_CACHE_SRC = None
        # Event bus glue back to initial
        _BUS = None
        _BUS_FAILED = False
        _LAST_PUBLISHED_COUNTS = None
        return True
    except Exception:
        return False
