"""Alert parity anomaly emission (Wave 4 – W4-15).

Emits structured event `pipeline.alert_parity.anomaly` when weighted alert parity difference
exceeds configured threshold.

Env Vars:
  G6_PARITY_ALERT_ANOMALY_THRESHOLD (float, default -1 => disabled)
  G6_PARITY_ALERT_ANOMALY_MIN_TOTAL (int, default 3) minimum union alert categories before considering anomaly

Event Payload Fields:
  event: pipeline.alert_parity.anomaly
  score: current parity score (float or None)
  weighted_diff_norm: normalized weighted diff (0..1)
  categories: per-category { legacy, pipeline, diff_norm, weight }
  threshold: threshold used
  parity_version: parity object version
  components: component scores map

Usage:
  maybe_emit_alert_parity_anomaly(parity_score_dict)

Safe no-op on errors or if disabled.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_NAME = 'pipeline.alert_parity.anomaly'

def _threshold() -> float:
    raw = os.getenv('G6_PARITY_ALERT_ANOMALY_THRESHOLD','-1').strip()
    try:
        return float(raw)
    except Exception:
        return -1.0

def _min_total() -> int:
    raw = os.getenv('G6_PARITY_ALERT_ANOMALY_MIN_TOTAL','3').strip()
    try:
        return int(raw)
    except Exception:
        return 3

def maybe_emit_alert_parity_anomaly(parity: dict[str, Any]) -> bool:
    """Emit structured anomaly event if weighted diff exceeds threshold.

    Returns True if event emitted, else False.
    """
    try:
        thr = _threshold()
        if thr < 0:
            return False  # disabled
        details = parity.get('details') if isinstance(parity, dict) else None
        if not isinstance(details, dict):
            return False
        alerts = details.get('alerts') if isinstance(details, dict) else None
        if not isinstance(alerts, dict):
            return False
        weighted = alerts.get('weighted_diff_norm')
        if weighted is None:
            # fallback to symmetric diff ratio if present
            union = alerts.get('union') or 0
            sym = alerts.get('sym_diff') or 0
            if union:
                weighted = float(sym)/float(union)
            else:
                return False
        try:
            weighted = float(weighted)
        except Exception:
            return False
        if weighted < thr:
            return False
        # Minimum union size condition to avoid noise on tiny sets
        union_count = 0
        if 'categories' in alerts and isinstance(alerts['categories'], dict):
            union_count = len(alerts['categories'])
        else:
            # approximate from union field or token sets
            union_count = alerts.get('union') or union_count
        if union_count < _min_total():
            return False
        payload = {
            'event': _EVENT_NAME,
            'ts': time.time(),
            'score': parity.get('score'),
            'weighted_diff_norm': weighted,
            'threshold': thr,
            'parity_version': parity.get('version'),
            'components': parity.get('components'),
        }
        # attach categories snippet if present
        cats = alerts.get('categories') if isinstance(alerts, dict) else None
        if isinstance(cats, dict):
            payload['categories'] = cats
        # Emission strategy: log JSON line with recognizable key
        logger.info(_EVENT_NAME, extra={'structured_event': payload})
        try:
            # Also write to stdout as JSON line if operator wants to tee (optional best-effort)
            if os.getenv('G6_STRUCT_LOG','0').lower() in ('1','true','yes','on'):
                print(json.dumps(payload, separators=(',',':')))
        except Exception:
            pass
        return True
    except Exception:
        logger.debug('parity_anomaly_emit_failed', exc_info=True)
        return False

__all__ = ['maybe_emit_alert_parity_anomaly']
