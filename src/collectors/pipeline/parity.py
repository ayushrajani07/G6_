#!/usr/bin/env python3
"""Parity scoring utilities for legacy vs pipeline collector outputs.

Objective: provide a stable, explainable score guiding promotion readiness.

Current heuristic (version 1):
  Inputs (dict-like) expected to contain at minimum:
    indices: list[dict | any] (length comparison)
    alerts: list[str] or list[dict]
    options_total: int (optional; else derived from indices aggregate if possible)

  Score components (0..1 each):
    index_count_component = 1 - min(1, abs(len_a - len_b) / max(1, len_a))
    option_count_component = 1 - min(1, abs(opt_a - opt_b) / max(1, opt_a))  (if available)
    alert_sym_diff_component = 1 - min(1, sym_diff_count / max(1, union_count))

  Overall score = weighted average (default weights all equal for present components).

Returned structure:
  {
    'version': 1,
    'components': {...},
    'weights': {...},
    'score': float,
    'missing': [...],    # components unavailable
    'details': {...},    # raw counts
  }

Future versions may incorporate distributional comparisons (e.g., per-index strike counts) but must remain monotonic and inexpensive.
"""
from __future__ import annotations
from typing import Any, Dict
from collections import deque
import os

def _extract_alert_set(obj: Any) -> set:
    if obj is None:
        return set()
    out = set()
    if isinstance(obj, (list, tuple, set)):
        for item in obj:
            if isinstance(item, str):
                out.add(item)
            elif isinstance(item, dict):
                # try canonical key forms
                for k in ('alert','name','type'):
                    v = item.get(k) if isinstance(item, dict) else None
                    if isinstance(v, str):
                        out.add(v)
                        break
    return out

def compute_parity_score(legacy: Dict[str, Any] | None, pipeline: Dict[str, Any] | None, *, weights: Dict[str, float] | None = None) -> Dict[str, Any]:
    extended = os.getenv('G6_PARITY_EXTENDED','0').lower() in ('1','true','on','yes')
    version = 2 if extended else 1
    if legacy is None or pipeline is None:
        return {'version': version, 'score': 0.0, 'components': {}, 'missing': ['all'], 'weights': {}, 'details': {}}
    weights = weights or {}
    # Default equal weights for found components; assign after detection.
    components: Dict[str, float] = {}
    details: Dict[str, Any] = {}
    missing: list[str] = []

    # Index count
    try:
        idx_a = legacy.get('indices') or []
        idx_b = pipeline.get('indices') or []
        la, lb = len(idx_a), len(idx_b)
        details['indices'] = (la, lb)
        comp_idx = 1 - min(1.0, abs(la - lb) / max(1, la))
        components['index_count'] = comp_idx
    except Exception:
        missing.append('index_count')

    # Option totals
    opt_a = legacy.get('options_total')
    opt_b = pipeline.get('options_total')
    if opt_a is None or opt_b is None:
        # Attempt derive from per-index counts if structure present
        def _derive(total_candidate):
            if not isinstance(total_candidate, list):
                return None
            total = 0
            for rec in total_candidate:
                if isinstance(rec, dict):
                    try:
                        total += int(rec.get('option_count') or 0)
                    except Exception:
                        pass
            return total
        if opt_a is None:
            opt_a = _derive(legacy.get('indices'))
        if opt_b is None:
            opt_b = _derive(pipeline.get('indices'))
    if opt_a is not None and opt_b is not None:
        try:
            details['options_total'] = (opt_a, opt_b)
            comp_opt = 1 - min(1.0, abs(opt_a - opt_b) / max(1, opt_a))
            components['option_count'] = comp_opt
        except Exception:
            missing.append('option_count')
    else:
        missing.append('option_count')

    # Alerts sym-diff (base + extended still same component name)
    try:
        al_a = _extract_alert_set(legacy.get('alerts'))
        al_b = _extract_alert_set(pipeline.get('alerts'))
        union = al_a | al_b
        sym = (al_a ^ al_b)
        details['alerts'] = {'union': len(union), 'sym_diff': len(sym)}
        comp_alerts = 1 - min(1.0, (len(sym) / max(1, len(union))))
        components['alerts'] = comp_alerts
    except Exception:
        missing.append('alerts')

    # Extended: strike coverage distribution similarity (simple mean diff heuristic)
    if extended:
        try:
            def _avg_cov(root):
                indices = root.get('indices') or []
                vals = []
                for rec in indices:
                    if isinstance(rec, dict):
                        sc = rec.get('strike_coverage_avg')
                        if isinstance(sc, (int, float)):
                            vals.append(float(sc))
                if not vals:
                    return None
                return sum(vals)/len(vals)
            avg_a = _avg_cov(legacy)
            avg_b = _avg_cov(pipeline)
            if avg_a is None or avg_b is None:
                missing.append('strike_coverage')
            else:
                details['strike_coverage_avg'] = (avg_a, avg_b)
                comp_cov = 1 - min(1.0, abs(avg_a - avg_b) / max(1e-9, abs(avg_a) if abs(avg_a) > 0 else 1.0))
                components['strike_coverage'] = comp_cov
        except Exception:
            missing.append('strike_coverage')

    # Assign weights if not provided
    if not weights:
        if components:
            w_each = 1.0 / len(components)
            weights = {k: w_each for k in components}
        else:
            weights = {}

    # Weighted score
    score = 0.0
    for k, v in components.items():
        score += v * weights.get(k, 0.0)

    return {
        'version': version,
        'score': round(score, 6),
        'components': components,
        'weights': weights,
        'missing': missing,
        'details': details,
    }

# Rolling parity aggregation (Wave 3)
_ROLLING_SCORES = deque()  # type: ignore[var-annotated]
_ROLLING_MAXLEN = 0

def record_parity_score(value: float | None) -> Dict[str, Any]:
    """Record a parity score into rolling window if enabled.

    Controlled by env var G6_PARITY_ROLLING_WINDOW (int, default 0 = disabled).
    Returns {'avg': float | None, 'count': int, 'window': int}.
    """
    global _ROLLING_SCORES, _ROLLING_MAXLEN
    try:
        window_raw = os.getenv('G6_PARITY_ROLLING_WINDOW','0')
        window = int(window_raw)
    except Exception:
        window = 0
    if window <= 1 or value is None:
        # Disabled or trivial window
        if window <= 1:
            return {'avg': value, 'count': 1 if value is not None else 0, 'window': window}
    # (Re)configure deque if window changed
    if window != _ROLLING_MAXLEN:
        _ROLLING_SCORES = deque(list(_ROLLING_SCORES)[-window:], maxlen=window)
        _ROLLING_MAXLEN = window
    _ROLLING_SCORES.append(value)
    if not _ROLLING_SCORES:
        return {'avg': None, 'count': 0, 'window': window}
    avg = sum(_ROLLING_SCORES)/len(_ROLLING_SCORES)
    return {'avg': avg, 'count': len(_ROLLING_SCORES), 'window': window}
