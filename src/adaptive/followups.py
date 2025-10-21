"""Adaptive Follow-Up Guards (Interpolation Guard, Risk Exposure Drift, Bucket Coverage Alert)

This module implements the forward-looking adaptive use cases outlined in docs/future_enhancements.md section 13.
Each guard evaluates rolling windows of recent metrics/state and can emit an internal event record plus
Prometheus counters to surface anomaly conditions. Actual adaptive controller feedback (e.g., throttling)
can hook into these signals in future iterations.

Guards:
 1. Interpolation Guard
    - If interpolated_fraction > threshold for N consecutive surface builds -> emit anomaly.
 2. Risk Exposure Drift
    - If absolute delta change in notional_delta over window exceeds drift_pct threshold while option count stable.
 3. Bucket Coverage Alert
    - If bucket utilization below threshold for M consecutive builds.

Environment Flags (document in env_dict.md):
  G6_FOLLOWUPS_INTERP_THRESHOLD (float, default 0.6)
  G6_FOLLOWUPS_INTERP_CONSEC (int, default 3)
  G6_FOLLOWUPS_RISK_DRIFT_PCT (float, default 0.25)
  G6_FOLLOWUPS_RISK_WINDOW (int, default 5)   # number of recent builds
  G6_FOLLOWUPS_RISK_MIN_OPTIONS (int, default 50) # ignore when very low option count
  G6_FOLLOWUPS_BUCKET_THRESHOLD (float, default 0.7)
  G6_FOLLOWUPS_BUCKET_CONSEC (int, default 10)
  G6_FOLLOWUPS_ENABLED (bool, default 1)

Metrics (group: adaptive_followups):
    g6_followups_interp_guard{index} counter
    g6_followups_risk_drift{index,sign} counter (sign=up|down)
    g6_followups_bucket_coverage{index} counter
    g6_followups_last_state{index,type} gauge (type=interp|risk|bucket) value encodes recent score (fraction, drift pct, utilization)

Thread-safety: accessed from orchestrator build paths single-threaded per index (current architecture) so
simple per-index in-memory buffers suffice.
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from prometheus_client import (
        REGISTRY,
        Counter,  # re-export for type checkers
        Gauge,
    )
    from prometheus_client import REGISTRY as _PromREGISTRY
    from prometheus_client import Counter as _PromCounter
    from prometheus_client import Gauge as _PromGauge
else:  # runtime dynamic import
    try:  # pragma: no cover - optional dependency
        from prometheus_client import REGISTRY as _PromREGISTRY
        from prometheus_client import Counter as _PromCounter
        from prometheus_client import Gauge as _PromGauge
    except Exception:  # pragma: no cover
        _PromCounter = _PromGauge = None  # type: ignore[assignment]
        _PromREGISTRY = None  # type: ignore[assignment]

    # Runtime aliases used by rest of module (typed as Any when missing)
    Counter: Any = _PromCounter  # type: ignore[assignment]
    Gauge: Any = _PromGauge  # type: ignore[assignment]
    REGISTRY: Any = _PromREGISTRY  # type: ignore[assignment]

def _import_event_bus_getter():  # lazy to avoid hard dependency
    try:
        from src.events import event_bus
        return getattr(event_bus, 'get_event_bus', None)
    except Exception:
        return None

_GET_EVENT_BUS = _import_event_bus_getter()

from . import severity  # for enriching emitted alerts (optional if severity enabled)

_GROUP = "adaptive_followups"

_interp_counter: Any = None
_risk_counter: Any = None
_bucket_counter: Any = None
_state_gauge: Any = None

@dataclass
class IndexBuffers:
    interp_consec: int = 0
    bucket_consec: int = 0
    risk_window: deque[float] | None = None
    risk_options: deque[int] | None = None

    def __post_init__(self):
        win = _env_int("G6_FOLLOWUPS_RISK_WINDOW", 5)
        if self.risk_window is None:
            self.risk_window = deque(maxlen=win)
        if self.risk_options is None:
            self.risk_options = deque(maxlen=win)

_buffers: dict[str, IndexBuffers] = {}

# Simple in-memory alert sink; orchestration layer can drain via get_and_clear_alerts().
_ALERTS: list[dict[str, Any]] = []  # legacy simple list (still exposed)

# Recent alerts ring buffer (for panels) and suppression/weight state
_RECENT_ALERTS: deque[dict[str, Any]] = deque(maxlen=int(os.getenv('G6_FOLLOWUPS_BUFFER_MAX','200') or 200))
_LAST_EMIT: dict[tuple[str,str], tuple[float,str]] = {}  # (index,type) -> (ts,last_severity)
_WEIGHT_EVENTS: deque[tuple[float,int]] = deque()  # (ts, weight)
_weight_pressure_gauge: Any = None  # gauge for rolling weight pressure

_BUS: Any | None = None
_BUS_FAILED = False


def _publish_event(event_type: str, payload: dict[str, Any], *, coalesce_key: str | None = None) -> None:
    global _BUS, _BUS_FAILED, _GET_EVENT_BUS
    if _GET_EVENT_BUS is None or _BUS_FAILED:
        return
    if _BUS is None:
        try:
            getter = _GET_EVENT_BUS
            if getter is None:
                _BUS_FAILED = True
                return
            candidate = getter()
            if not hasattr(candidate, 'publish'):
                _BUS_FAILED = True
                return
            _BUS = candidate
        except Exception:
            _BUS_FAILED = True
            return
    try:
        if _BUS is not None:
            _BUS.publish(event_type, payload, coalesce_key=coalesce_key)
    except Exception:
        pass

def _now() -> float:
    import time as _t
    return _t.time()

def _suppression_seconds() -> int:
    try:
        return int(os.getenv('G6_FOLLOWUPS_SUPPRESS_SECONDS','60') or 60)
    except Exception:
        return 60

def _weight_window() -> int:
    try:
        return int(os.getenv('G6_FOLLOWUPS_WEIGHT_WINDOW','300') or 300)
    except Exception:
        return 300

_WEIGHTS_CACHE: dict[str, dict[str,int]] | None = None

def _load_weights() -> dict[str, dict[str,int]]:
    global _WEIGHTS_CACHE
    if _WEIGHTS_CACHE is not None:
        return _WEIGHTS_CACHE
    raw = os.getenv('G6_FOLLOWUPS_WEIGHTS','')
    parsed: dict[str, dict[str,int]] = {}
    if raw:
        try:
            import json
            obj = json.loads(raw)
            if isinstance(obj, dict):
                for k,v in obj.items():
                    if isinstance(v, dict):
                        pv = {}
                        for sk, sv in v.items():
                            try:
                                pv[str(sk)] = int(sv)
                            except Exception:
                                continue
                        if pv:
                            parsed[str(k)] = pv
        except Exception:  # pragma: no cover
            parsed = {}
    _WEIGHTS_CACHE = parsed
    return parsed

def _weight_for(alert: dict[str, Any]) -> int:
    weights = _load_weights()
    atype = alert.get('type')
    sev = alert.get('severity') or 'info'
    if atype in weights:
        return weights[atype].get(str(sev), 0)
    return 0

def _record_weight(alert: dict[str, Any]) -> int:
    w = _weight_for(alert)
    if w <= 0:
        return 0
    ts = _now()
    _WEIGHT_EVENTS.append((ts, w))
    # purge old
    cutoff = ts - _weight_window()
    while _WEIGHT_EVENTS and _WEIGHT_EVENTS[0][0] < cutoff:
        _WEIGHT_EVENTS.popleft()
    return w

def get_weight_pressure() -> int:
    ts = _now()
    cutoff = ts - _weight_window()
    total = 0
    # purge on read
    while _WEIGHT_EVENTS and _WEIGHT_EVENTS[0][0] < cutoff:
        _WEIGHT_EVENTS.popleft()
    for _, w in _WEIGHT_EVENTS:
        total += w
    try:
        if _weight_pressure_gauge is not None:
            _weight_pressure_gauge.set(total)
    except Exception:
        pass
    return total

# Debug flag: when enabled exposes richer state via get_debug_state(); cheap to call.
_DEBUG = os.getenv('G6_FOLLOWUPS_DEBUG','').lower() in ('1','true','yes','on')

_initialized = False

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default

def _env_bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(int(1 if default else 0))) in ("1","true","True","yes","on")

def _maybe_register_metrics():
    """Idempotently register follow-up guard metrics (concise helper).

    Uses a simple create-or-reuse pattern: attempt creation; on ValueError (already registered)
    walk registry mapping to retrieve existing collector reference. This keeps logic small and
    avoids pre-collect enumeration of all metric families.
    """
    global _initialized, _interp_counter, _risk_counter, _bucket_counter, _state_gauge, _weight_pressure_gauge
    if _initialized:
        return
    _initialized = True  # set early to avoid re-entrancy loops
    if not _env_bool("G6_FOLLOWUPS_ENABLED", True) or Counter is None or Gauge is None:  # pragma: no cover - gating
        return
    def _get_existing(name: str):  # minimal internal helper
        if REGISTRY is None:
            return None
        try:
            mapping = getattr(REGISTRY, '_collector_to_names', {})
            for col, names in mapping.items():
                if any(n == name or n == f"{name}_total" for n in names):
                    return col
        except Exception:
            return None
        return None

    def _register(kind: str, obj_ref_name: str, ctor, *labels):  # noqa: ANN001 - internal
        global _interp_counter, _risk_counter, _bucket_counter, _state_gauge, _weight_pressure_gauge
        target = None
        try:
            target = ctor(kind, FOLLOWUP_METRIC_HELP[kind], list(labels))
        except Exception:
            target = _get_existing(kind)
        if target is None:  # second-chance lookup (race or prior partial registration)
            target = _get_existing(kind)
        if obj_ref_name == 'interp':
            _interp_counter = target
        elif obj_ref_name == 'risk':
            _risk_counter = target
        elif obj_ref_name == 'bucket':
            _bucket_counter = target
        elif obj_ref_name == 'state':
            _state_gauge = target
        elif obj_ref_name == 'weight_pressure':
            _weight_pressure_gauge = target

    # Help text map kept near registration for clarity
    FOLLOWUP_METRIC_HELP: dict[str, str] = {
        'g6_followups_interp_guard': 'Interpolation guard trigger count',
        'g6_followups_risk_drift': 'Risk exposure drift trigger count',
        'g6_followups_bucket_coverage': 'Bucket coverage low trigger count',
        'g6_followups_last_state': 'Last measured followup state value (fraction, drift pct, utilization)',
        'g6_followups_weight_pressure': 'Rolling accumulated weight for follow-up alerts (windowed)',
    }

    _register('g6_followups_interp_guard', 'interp', Counter, 'index')
    _register('g6_followups_risk_drift', 'risk', Counter, 'index','sign')
    _register('g6_followups_bucket_coverage', 'bucket', Counter, 'index')
    _register('g6_followups_last_state', 'state', Gauge, 'index','type')
    _register('g6_followups_weight_pressure', 'weight_pressure', Gauge)


def record_surface_metrics(index: str, interpolated_fraction: float, bucket_utilization: float | None):
    """Feed volatility surface build outputs into follow-up guards.
    Called after each surface build.
    """
    _maybe_register_metrics()
    if not _env_bool("G6_FOLLOWUPS_ENABLED", True):
        return
    buf = _buffers.setdefault(index, IndexBuffers())
    # Interpolation Guard
    interp_threshold = _env_float("G6_FOLLOWUPS_INTERP_THRESHOLD", 0.6)
    interp_consec_req = _env_int("G6_FOLLOWUPS_INTERP_CONSEC", 3)
    if interpolated_fraction > interp_threshold:
        buf.interp_consec += 1
    else:
        buf.interp_consec = 0
    if _state_gauge:
        _state_gauge.labels(index=index, type="interp").set(interpolated_fraction)
    if buf.interp_consec >= interp_consec_req and _interp_counter:
        _interp_counter.labels(index=index).inc()
        alert = {"type": "interpolation_high", "index": index, "interpolated_fraction": interpolated_fraction, "message": f"interp_fraction={interpolated_fraction:.2f}"}
        _emit_alert(alert)
        buf.interp_consec = 0  # reset after trigger

    # Bucket Coverage Alert
    if bucket_utilization is not None:
        bucket_threshold = _env_float("G6_FOLLOWUPS_BUCKET_THRESHOLD", 0.7)
        bucket_consec_req = _env_int("G6_FOLLOWUPS_BUCKET_CONSEC", 10)
        if bucket_utilization < bucket_threshold:
            buf.bucket_consec += 1
        else:
            buf.bucket_consec = 0
        if _state_gauge:
            _state_gauge.labels(index=index, type="bucket").set(bucket_utilization)
        if buf.bucket_consec >= bucket_consec_req and _bucket_counter:
            _bucket_counter.labels(index=index).inc()
            alert = {"type": "bucket_util_low", "index": index, "utilization": bucket_utilization, "message": f"bucket_util={bucket_utilization:.2f}"}
            _emit_alert(alert)
            buf.bucket_consec = 0


def record_risk_notional(index: str, notional_delta: float, option_count: int):
    """Feed risk aggregation outputs into drift guard."""
    _maybe_register_metrics()
    if not _env_bool("G6_FOLLOWUPS_ENABLED", True):
        return
    buf = _buffers.setdefault(index, IndexBuffers())
    if buf.risk_window is None:
        buf.risk_window = deque(maxlen=_env_int("G6_FOLLOWUPS_RISK_WINDOW", 5))
    if buf.risk_options is None:
        buf.risk_options = deque(maxlen=_env_int("G6_FOLLOWUPS_RISK_WINDOW", 5))
    buf.risk_window.append(notional_delta)
    buf.risk_options.append(option_count)
    if _state_gauge:
        rw_local = buf.risk_window
        if rw_local and len(rw_local) >= 2:
            prev = rw_local[0]
            latest = rw_local[-1]
            base = max(abs(prev), 1.0)
            drift_pct = abs(latest - prev) / base
            _state_gauge.labels(index=index, type="risk").set(drift_pct)
        else:
            _state_gauge.labels(index=index, type="risk").set(0.0)
    # Evaluate drift only if window full
    window_len = _env_int("G6_FOLLOWUPS_RISK_WINDOW", 5)
    rw2 = buf.risk_window
    ro2 = buf.risk_options
    if rw2 and ro2 and len(rw2) == window_len:
        if max(ro2) >= _env_int("G6_FOLLOWUPS_RISK_MIN_OPTIONS", 50):
            mean_options = sum(ro2) / window_len
            diff_range = max(ro2) - min(ro2)
            if mean_options > 0 and diff_range / mean_options < 0.05:
                first = rw2[0]
                last = rw2[-1]
                base = max(abs(first), 1.0)
                drift_pct = (last - first) / base
                if abs(drift_pct) >= _env_float("G6_FOLLOWUPS_RISK_DRIFT_PCT", 0.25):
                    sign = "up" if drift_pct > 0 else "down"
                    if _risk_counter:
                        try:
                            _risk_counter.labels(index=index, sign=sign).inc()
                        except Exception:
                            pass
                    alert = {"type": "risk_delta_drift", "index": index, "drift_pct": drift_pct, "message": f"drift_pct={drift_pct:.3f}", "sign": sign}
                    _emit_alert(alert)
                    try:
                        rw2.popleft()
                        ro2.popleft()
                    except Exception:
                        pass

# Convenience composite feed for orchestrator if both surface & risk info in hand

def feed(index: str, interpolated_fraction: float | None=None, bucket_utilization: float | None=None, notional_delta: float | None=None, option_count: int | None=None):
    # Invoke surface metrics path if either interpolation fraction or bucket utilization provided.
    if interpolated_fraction is not None or bucket_utilization is not None:
        record_surface_metrics(index, interpolated_fraction if interpolated_fraction is not None else 0.0, bucket_utilization)
    if notional_delta is not None and option_count is not None:
        record_risk_notional(index, notional_delta, option_count)


def get_and_clear_alerts() -> list[dict[str, Any]]:
    """Return and clear accumulated follow-up alerts.

    Orchestrator can periodically drain this and merge into adaptive_alerts list.
    """
    if not _ALERTS:
        return []
    out = list(_ALERTS)
    _ALERTS.clear()
    return out

def _emit_alert(alert: dict[str, Any]) -> None:
    # Enrich severity if enabled
    try:
        alert = severity.enrich_alert(alert)
    except Exception:
        pass
    # Suppression logic with escalation bypass
    sev_key = str(alert.get('severity') or 'info')
    key = (str(alert.get('index')), str(alert.get('type')))
    now_ts = _now()
    sup = _suppression_seconds()
    last = _LAST_EMIT.get(key)
    if last is not None:
        last_ts, last_sev = last
        if (now_ts - last_ts) < sup:
            order = {'info':0,'warn':1,'critical':2}
            # suppress if not strictly higher severity
            if order.get(sev_key,0) <= order.get(last_sev,0):
                return
    _LAST_EMIT[key] = (now_ts, sev_key)
    alert['ts'] = now_ts
    _ALERTS.append(alert)
    _RECENT_ALERTS.append(alert)
    # Weight tracking
    weight_value = _record_weight(alert)
    weight_pressure = get_weight_pressure()
    # Event log emission
    if os.getenv('G6_FOLLOWUPS_EVENTS','1').lower() in ('1','true','yes','on'):
        try:
            from src.events import event_log
            event_log.dispatch('followup_alert', level='info', index=alert.get('index'), context={k:v for k,v in alert.items() if k not in {'index'}})
        except Exception:
            pass

    idx = str(alert.get('index') or 'unknown')
    atype = str(alert.get('type') or 'unknown')
    payload: dict[str, Any] = {
        'alert': dict(alert),
        'index': idx,
        'type': atype,
        'severity': alert.get('severity'),
        'active_severity': alert.get('active_severity'),
        'message': alert.get('message'),
        'ts': alert.get('ts'),
        'weight': weight_value,
        'weight_pressure': weight_pressure,
        'resolved': alert.get('resolved', False),
    }
    if 'cycle' in alert:
        payload['cycle'] = alert.get('cycle')
    counts_snapshot: dict[str, int] | None
    try:
        counts_val = severity.get_active_severity_counts()
        counts_snapshot = {k: int(counts_val.get(k, 0)) for k in ('info', 'warn', 'critical')}
    except Exception:
        counts_snapshot = None
    if counts_snapshot is None:
        counts_snapshot = {'info': 0, 'warn': 0, 'critical': 0}
    sev_key = str(alert.get('active_severity') or alert.get('severity') or 'info').lower()
    if sev_key not in counts_snapshot:
        sev_key = 'info'
    if all(v == 0 for v in counts_snapshot.values()):
        counts_snapshot[sev_key] = counts_snapshot.get(sev_key, 0) + 1
    payload['severity_counts'] = counts_snapshot
    _publish_event(
        'followup_alert',
        payload,
        coalesce_key=f'followup:{idx}:{atype}',
    )

def get_recent_alerts(limit: int = 50) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    if limit >= len(_RECENT_ALERTS):
        return list(_RECENT_ALERTS)
    return list(list(_RECENT_ALERTS)[-limit:])

def get_debug_state() -> dict[str, Any]:  # pragma: no cover - debug utility
    if not _DEBUG:
        return {}
    snap = {}
    for idx, buf in _buffers.items():
        snap[idx] = {
            'interp_consec': buf.interp_consec,
            'bucket_consec': buf.bucket_consec,
            'risk_window': list(buf.risk_window) if buf.risk_window else [],
            'risk_options': list(buf.risk_options) if buf.risk_options else [],
        }
    return {
        'buffers': snap,
        'pending_alerts': len(_ALERTS),
        'enabled': _env_bool('G6_FOLLOWUPS_ENABLED', True),
    }

__all__ = [
    'feed','record_surface_metrics','record_risk_notional','get_and_clear_alerts','get_debug_state','get_recent_alerts','get_weight_pressure'
]
