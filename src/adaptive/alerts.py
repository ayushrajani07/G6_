"""Adaptive analytics alert tracking helpers.

Provides lightweight stateful utilities for:
 - Interpolation fraction streak alerting
 - Risk delta drift detection
 - Bucket utilization low streak detection

State is stored on the metrics singleton to avoid new global singletons and to
piggy-back existing lifecycle and testing reset mechanisms.

Environment flags (all optional):
  G6_INTERP_FRACTION_ALERT_THRESHOLD   (float, default 0.6)
  G6_INTERP_FRACTION_ALERT_STREAK      (int, default 5)
  G6_RISK_DELTA_DRIFT_PCT              (float percent, default 25)
  G6_RISK_DELTA_DRIFT_WINDOW           (int builds, default 5)
  G6_RISK_DELTA_STABLE_ROW_TOLERANCE   (float fraction, default 0.05)
  G6_RISK_BUCKET_UTIL_MIN              (float, default 0.7)
  G6_RISK_BUCKET_UTIL_STREAK           (int, default 5)

Alert surfacing contract:
Each trigger returns a dict {type, message}. Callers can aggregate and attach
into runtime status under key 'adaptive_alerts'.
"""
from __future__ import annotations

import os
from typing import Any

from . import severity


def _get_metrics():  # lightweight guarded import to avoid attr-defined ignores
    try:
        from src.metrics import get_metrics as _gm  # facade import
        return _gm()
    except Exception:
        return None

def _get_or_init_dict(obj: Any, attr: str) -> dict[str, Any]:
    d = getattr(obj, attr, None)
    if not isinstance(d, dict):
        d = {}
        try:
            setattr(obj, attr, d)
        except Exception:
            pass
    return d

def _get_or_init_list(obj: Any, attr: str) -> list[Any]:
    lst = getattr(obj, attr, None)
    if not isinstance(lst, list):
        lst = []
        try:
            setattr(obj, attr, lst)
        except Exception:
            pass
    return lst

def _get_or_init_int(obj: Any, attr: str) -> int:
    val = getattr(obj, attr, None)
    if not isinstance(val, int):
        val = 0
        try:
            setattr(obj, attr, val)
        except Exception:
            pass
    return val

# Utility env helpers

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

# ---------------- Interpolation Guard -----------------

def record_interpolation_fraction(index: str, fraction: float) -> dict[str, Any] | None:
    m = _get_metrics()
    if m is None:
        return None
    thr = _env_float('G6_INTERP_FRACTION_ALERT_THRESHOLD', 0.6)
    streak_target = _env_int('G6_INTERP_FRACTION_ALERT_STREAK', 5)
    # Streak state attribute per index (dict on metrics)
    streaks = _get_or_init_dict(m, '_interp_streak')
    cur = streaks.get(index, 0)
    if fraction > thr:
        cur += 1
    else:
        cur = 0
    streaks[index] = cur
    # Optional lightweight debug trace to help diagnose missing alert emission in tests.
    # Enabled only when G6_INTERP_DEBUG env flag is truthy; avoids noisy logs otherwise.
    if os.getenv('G6_INTERP_DEBUG','').lower() in {'1','true','yes','on'}:
        try:  # pragma: no cover - debug path
            print(f"[interp-debug] idx={index} fraction={fraction} thr={thr} streak={cur}/{streak_target} metrics_id={id(m)}", flush=True)
        except Exception:
            pass
    try:
        ais = getattr(m, 'adaptive_interpolation_streak', None)
        if ais is not None and hasattr(ais, 'labels'):
            ais.labels(index=index).set(cur)
    except Exception:
        pass
    if cur >= streak_target and fraction > thr:
        # Fire alert
        if os.getenv('G6_INTERP_DEBUG','').lower() in {'1','true','yes','on'}:
            try:  # pragma: no cover
                print(f"[interp-debug] ALERT FIRING idx={index} fraction={fraction} streak={cur} thr={thr} target={streak_target}", flush=True)
            except Exception:
                pass
        try:
            aia = getattr(m, 'adaptive_interpolation_alerts', None)
            if aia is not None and hasattr(aia, 'labels'):
                aia.labels(index=index, reason='high_fraction').inc()
        except Exception:
            pass
        alert_obj: dict[str, Any] = {
            'type': 'interpolation_high',
            'message': f'interpolated fraction {fraction:.2f} > {thr:.2f} for {cur} consecutive builds ({index})',
            'interpolated_fraction': fraction,
        }
        severity.enrich_alert(alert_obj)
        try:
            alerts_list = getattr(m, 'adaptive_alerts', None)
            if alerts_list is None:
                m.adaptive_alerts = [alert_obj]
            else:
                if isinstance(alerts_list, list):
                    alerts_list.append(alert_obj)
        except Exception:
            pass
        return alert_obj
    return None

# ---------------- Risk Delta Drift -----------------

def record_risk_delta(delta_notional: float, row_count: int) -> dict[str, Any] | None:
    m = _get_metrics()
    if m is None:
        return None
    pct_threshold = _env_float('G6_RISK_DELTA_DRIFT_PCT', 25.0)
    window = _env_int('G6_RISK_DELTA_DRIFT_WINDOW', 5)
    row_tol = _env_float('G6_RISK_DELTA_STABLE_ROW_TOLERANCE', 0.05)
    buf = _get_or_init_list(m, '_risk_delta_window')  # list of (delta,row_count)
    # type narrowing runtime
    if buf and not all(isinstance(t, tuple) and len(t) == 2 for t in buf):
        buf.clear()
    buf.append((delta_notional, row_count))
    if len(buf) > window:
        buf.pop(0)
    if len(buf) < window:
        return None  # insufficient samples
    first_delta, first_rows = buf[0]
    last_delta, last_rows = buf[-1]
    # Row stability check
    if first_rows > 0:
        row_change_frac = abs(last_rows - first_rows) / float(first_rows)
        if row_change_frac > row_tol:
            return None
    if first_delta == 0:
        return None
    change_pct = (last_delta - first_delta) / abs(first_delta) * 100.0
    try:
        arlcp = getattr(m, 'adaptive_risk_delta_last_change_pct', None)
        if arlcp is not None and hasattr(arlcp, 'set'):
            arlcp.set(abs(change_pct))
    except Exception:
        pass
    if abs(change_pct) >= pct_threshold:
        direction = 'up' if change_pct > 0 else 'down'
        try:
            ard = getattr(m, 'adaptive_risk_delta_drift_alerts', None)
            if ard is not None and hasattr(ard, 'labels'):
                ard.labels(direction=direction).inc()
        except Exception:
            pass
        alert_obj: dict[str, Any] = {
            'type': 'risk_delta_drift',
            'message': f'risk delta drift {change_pct:+.1f}% over {window} builds with stable rows',
            'drift_pct': change_pct,
        }
        severity.enrich_alert(alert_obj)
        return alert_obj
    return None

# ---------------- Bucket Utilization Streak -----------------

def record_bucket_util(utilization: float) -> dict[str, Any] | None:
    m = _get_metrics()
    if m is None:
        return None
    thr = _env_float('G6_RISK_BUCKET_UTIL_MIN', 0.7)
    streak_target = _env_int('G6_RISK_BUCKET_UTIL_STREAK', 5)
    cur = _get_or_init_int(m, '_bucket_util_streak')
    if utilization < thr:
        cur += 1
    else:
        cur = 0
    try:
        m._bucket_util_streak = cur
    except Exception:
        pass
    try:
        abus = getattr(m, 'adaptive_bucket_util_streak', None)
        if abus is not None and hasattr(abus, 'set'):
            abus.set(cur)
    except Exception:
        pass
    if cur >= streak_target and utilization < thr:
        try:
            abua = getattr(m, 'adaptive_bucket_util_alerts', None)
            if abua is not None and hasattr(abua, 'inc'):
                abua.inc()
        except Exception:
            pass
        alert_obj: dict[str, Any] = {
            'type': 'bucket_util_low',
            'message': f'bucket utilization {utilization:.2f} < {thr:.2f} for {cur} consecutive builds',
            'utilization': utilization,
        }
        severity.enrich_alert(alert_obj)
        return alert_obj
    return None

__all__ = ['record_interpolation_fraction','record_risk_delta','record_bucket_util']
