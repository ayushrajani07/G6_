#!/usr/bin/env python3
"""Central error routing registry.

Purpose: Provide a single table-driven mechanism to classify and act on error events.
Initial version is intentionally minimal; future integration can replace ad-hoc
logging/metric sites with `route_error` calls.

Route Actions:
  - log_level: one of 'debug','info','warning','error'
  - metric: optional metric name to increment (labels merged)
  - suppress: if True, caller may choose not to re-log upstream
  - escalate_env: environment variable name; if set truthy escalates log level by one

Example:
    route_error('csv.mixed_expiry.prune', logger, metrics, index='NIFTY', dropped=12)
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

# Registry definition (seed with a few exemplar entries mirroring existing patterns)
# Registry can now include:
#   log_level, metric, suppress, escalate_env,
#   severity (string), throttle_sec (float), serializer (callable)
ERROR_REGISTRY: dict[str, dict[str, Any]] = {
    'csv.mixed_expiry.prune': {
        'log_level': 'info',
        'metric': 'csv_mixed_expiry_dropped',
    },
    'csv.schema.issues': {
        'log_level': 'warning',
        'metric': 'data_errors_labeled',
    },
    'csv.junk.skip': {
        'log_level': 'debug',  # often verbose
        'metric': 'csv_junk_rows_skipped',
    },
    'csv.expiry.misclass': {
        'log_level': 'warning',
        'metric': 'expiry_misclassification_total',
    },
}

_LEVEL_ORDER = ['debug','info','warning','error','critical']
_SEVERITY_DEFAULT = {
    'debug': 'low',
    'info': 'low',
    'warning': 'medium',
    'error': 'high',
    'critical': 'critical'
}

_THROTTLE_CACHE: dict[str, float] = {}
_LOCK = threading.Lock()

def _escalate(level: str) -> str:
    try:
        idx = _LEVEL_ORDER.index(level)
        return _LEVEL_ORDER[min(idx+1, len(_LEVEL_ORDER)-1)]
    except ValueError:
        return level

def register_error(code: str, **spec) -> None:
    """Register or update an error route at runtime."""
    ERROR_REGISTRY[code] = spec

def unregister_error(code: str) -> None:
    ERROR_REGISTRY.pop(code, None)

def _serialize_labels(labels: dict[str, Any]) -> tuple[dict[str,str], str | None]:
    safe: dict[str,str] = {}
    err: str | None = None
    for k,v in labels.items():
        if not isinstance(k,str):
            continue
        if isinstance(v,(str,int,float,bool)) or v is None:
            safe[k] = str(v)
            continue
        try:
            safe[k] = json.dumps(v, default=str)[:512]
        except Exception:
            safe[k] = '<unserializable>'
            err = f'serialize_fail:{k}'
    return safe, err

def route_error(code: str, logger, metrics=None, _count: int | float = 1, **labels):
    """Route an error/event code through the registry with enhancements.

    Enhancements:
      - Severity (derived if absent)
      - Throttling via throttle_sec
      - Safe label serialization for metrics/logs
      - Dynamic registration helpers
    Returns dict for test/assertion.
    """
    ts = time.time()
    try:
        spec = ERROR_REGISTRY.get(code)
        if not spec:
            if logger:
                try:
                    logger.debug(f"UNREGISTERED_ERROR code={code} labels={labels}")
                except Exception:
                    pass
            return {'code': code, 'registered': False}
        log_level = spec.get('log_level','info')
        escalator = spec.get('escalate_env')
        if escalator and os.environ.get(escalator,'0').lower() in ('1','true','yes','on'):
            log_level = _escalate(log_level)
        throttle_sec = spec.get('throttle_sec')
        throttle_key = f"{code}:{log_level}"
        throttled = False
        if throttle_sec:
            with _LOCK:
                last = _THROTTLE_CACHE.get(throttle_key)
                if last and ts - last < throttle_sec:
                    throttled = True
                else:
                    _THROTTLE_CACHE[throttle_key] = ts
        safe_labels, ser_err = _serialize_labels(labels)
        severity = spec.get('severity') or _SEVERITY_DEFAULT.get(log_level,'low')
        if ser_err:
            safe_labels['serialization_issue'] = ser_err
        msg = f"ROUTE_ERROR code={code} severity={severity} labels={safe_labels}"
        if throttled:
            msg += " throttled=1"
        try:
            if not throttled and logger and hasattr(logger, log_level):
                getattr(logger, log_level)(msg)
            elif throttled and logger and hasattr(logger,'debug'):
                logger.debug(msg)
        except Exception:
            pass
        metric_name = spec.get('metric')
        metric_result = None
        if metrics and metric_name and hasattr(metrics, metric_name):
            try:
                m = getattr(metrics, metric_name)
                if hasattr(m, 'labels'):
                    m.labels(**safe_labels).inc(_count)
                else:
                    m.inc(_count)
                metric_result = metric_name
            except Exception:
                metric_result = None
        return {
            'code': code,
            'registered': True,
            'log_level': log_level,
            'severity': severity,
            'metric': metric_result,
            'throttled': throttled
        }
    except Exception:
        return {'code': code, 'registered': False, 'error': 'route_failed'}
