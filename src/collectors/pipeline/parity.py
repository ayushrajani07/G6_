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

import os
from collections import deque
from typing import Any, TypedDict


def _extract_alert_set(obj: Any) -> set[str]:
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

class ParityDetails(TypedDict, total=False):
    indices: tuple[int, int]
    options_total: tuple[int, int]
    alerts: dict[str, Any]
    strike_coverage_avg: tuple[float, float]
    strike_shape: dict[str, Any]
    strike_cov_variance: dict[str, Any]

class ParityResult(TypedDict, total=False):
    version: int
    score: float
    components: dict[str, float]
    weights: dict[str, float]
    missing: list[str]
    details: ParityDetails


def compute_parity_score(legacy: dict[str, Any] | None, pipeline: dict[str, Any] | None, *, weights: dict[str, float] | None = None) -> ParityResult:
    extended = os.getenv('G6_PARITY_EXTENDED','0').lower() in ('1','true','on','yes')
    enable_shape = os.getenv('G6_PARITY_STRIKE_SHAPE','0').lower() in ('1','true','on','yes')
    enable_cov_var = os.getenv('G6_PARITY_STRIKE_COV_VAR','0').lower() in ('1','true','on','yes')
    # Version bump logic: base v1 + (extended) + (shape) + (cov_var) to represent feature provenance
    version = 1
    if extended:
        version += 1  # becomes 2
    if enable_shape:
        version += 1  # becomes 2 or 3 depending on extended flag
    if enable_cov_var:
        version += 1
    if legacy is None or pipeline is None:
        return {'version': version, 'score': 0.0, 'components': {}, 'missing': ['all'], 'weights': {}, 'details': {}}
    weights = weights or {}
    # Default equal weights for found components; assign after detection.
    components: dict[str, float] = {}
    details: ParityDetails = {}
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
        def _derive(total_candidate: Any) -> int | None:
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

    # Alerts parity (supports optional severity weighting + per-category diff)
    try:
        # Accept either flat list (legacy) or structured {'categories': {...}}
        def _normalize_alerts(root: dict[str, Any]) -> dict[str, int]:
            if root is None:
                return {}
            alerts_block = root.get('alerts') if isinstance(root, dict) else None
            if isinstance(alerts_block, dict):
                cats = alerts_block.get('categories') if isinstance(alerts_block, dict) else None
                if isinstance(cats, dict):
                    norm: dict[str,int] = {}
                    for k, v in cats.items():
                        try:
                            norm[str(k)] = int(v)
                        except Exception:
                            continue
                    return norm
            seq = root.get('alerts') if isinstance(root, dict) else None
            if isinstance(seq, (list, tuple, set)):
                tokens = _extract_alert_set(seq)
                return {t: 1 for t in tokens}
            return {}
        cats_a = _normalize_alerts(legacy) if legacy else {}
        cats_b = _normalize_alerts(pipeline) if pipeline else {}
        # Union of category names
        cat_names = sorted(set(cats_a.keys()) | set(cats_b.keys()))
        # Severity weighting env override: comma list cat:weight
        raw_weights = os.getenv('G6_PARITY_ALERT_WEIGHTS','')
        sev_weights: dict[str, float] = {}
        if raw_weights:
            for part in raw_weights.split(','):
                if not part.strip():
                    continue
                if ':' in part:
                    k, val = part.split(':',1)
                    try:
                        sev_weights[k.strip()] = float(val)
                    except Exception:
                        continue
        # Default weight =1.0
        diffs_weighted = 0.0
        denom_weighted = 0.0
        per_cat_details = {}
        for name in cat_names:
            a = cats_a.get(name, 0)
            b = cats_b.get(name, 0)
            w = sev_weights.get(name, 1.0)
            diff_raw = abs(a - b)
            # treat presence difference proportionally – normalization by max(a,1)
            ref = max(1, a)
            contrib = min(1.0, diff_raw / ref)
            diffs_weighted += contrib * w
            denom_weighted += w
            per_cat_details[name] = {'legacy': a, 'pipeline': b, 'weight': w, 'diff_norm': round(contrib,4)}
        if denom_weighted == 0:
            # fall back to original symmetric diff approach
            al_a = _extract_alert_set(legacy.get('alerts') if legacy else [])
            al_b = _extract_alert_set(pipeline.get('alerts') if pipeline else [])
            union = al_a | al_b
            sym = (al_a ^ al_b)
            details['alerts'] = {'union': len(union), 'sym_diff': len(sym)}
            comp_alerts = 1 - min(1.0, (len(sym) / max(1, len(union))))
        else:
            normalized = diffs_weighted / denom_weighted
            comp_alerts = 1 - min(1.0, normalized)
            details['alerts'] = {
                'categories': per_cat_details,
                'weighted_diff_norm': round(normalized,6),
                'weights_applied': bool(raw_weights),
            }
        components['alerts'] = comp_alerts
    except Exception:
        missing.append('alerts')

    # Extended: strike coverage distribution similarity (simple mean diff heuristic)
    if extended:
        try:
            def _avg_cov(root: dict[str, Any]) -> float | None:
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

    # Strike shape distribution component (Wave 4 W4-07)
    if enable_shape:
        try:
            # Extract per-index strike counts; fallback to option_count where strike_count missing
            def _strike_counts(root: dict[str, Any]) -> list[int]:
                out: list[int] = []
                indices = root.get('indices') or []
                for rec in indices:
                    if not isinstance(rec, dict):
                        continue
                    # Attempt per-expiry strike counts first (flatten)
                    _exp_val = rec.get('expiries')
                    expiries = _exp_val if isinstance(_exp_val, list) else []
                    added = False
                    for exp in expiries:
                        if isinstance(exp, dict):
                            sc = exp.get('strike_coverage')  # sometimes ratio, not a count
                            if isinstance(sc, (int, float)) and sc == sc and sc >= 0:
                                # skip ratio-like coverage metrics >1? treat as count only if integerish
                                if float(sc).is_integer():
                                    out.append(int(sc))
                                    added = True
                    # Fallback to option_count
                    if not added:
                        oc = rec.get('option_count')
                        if isinstance(oc, (int, float)) and oc >= 0:
                            out.append(int(oc))
                return out
            counts_a = _strike_counts(legacy) if legacy else []
            counts_b = _strike_counts(pipeline) if pipeline else []
            # Need at least 2 bins each to be meaningful
            if len(counts_a) < 1 or len(counts_b) < 1:
                missing.append('strike_shape')
            else:
                # Normalize to probability vectors
                sum_a = sum(counts_a) or 1
                sum_b = sum(counts_b) or 1
                # Pad shorter list with zeros for positional comparison after sorting for order invariance
                counts_a_sorted = sorted(counts_a, reverse=True)
                counts_b_sorted = sorted(counts_b, reverse=True)
                L = max(len(counts_a_sorted), len(counts_b_sorted))
                counts_a_sorted.extend([0]*(L - len(counts_a_sorted)))
                counts_b_sorted.extend([0]*(L - len(counts_b_sorted)))
                pa = [c / sum_a for c in counts_a_sorted]
                pb = [c / sum_b for c in counts_b_sorted]
                # L1 distance (total variation distance *2): tvd = 0.5 * sum |pa - pb|; component = 1 - tvd
                l1 = 0.0
                for i in range(L):
                    try:
                        l1 += abs(pa[i] - pb[i])
                    except Exception:
                        l1 += 0.0
                tvd = 0.5 * l1
                if tvd < 0:  # safety
                    tvd = 0.0
                comp_shape = 1 - min(1.0, tvd)
                components['strike_shape'] = comp_shape
                details['strike_shape'] = {
                    'distance': round(tvd, 6),
                    'bins': L,
                    'legacy_counts': counts_a_sorted[:L],
                    'pipeline_counts': counts_b_sorted[:L],
                }
        except Exception:
            missing.append('strike_shape')

    # Strike coverage variance component (Wave 4 W4-08)
    if enable_cov_var:
        try:
            def _cov_vals(root: dict[str, Any]) -> list[float]:
                vals: list[float] = []
                indices = root.get('indices') or []
                for rec in indices:
                    if isinstance(rec, dict):
                        sca = rec.get('strike_coverage_avg')
                        if isinstance(sca, (int, float)) and sca == sca:  # not NaN
                            vals.append(float(sca))
                return vals
            vals_a = _cov_vals(legacy) if legacy else []
            vals_b = _cov_vals(pipeline) if pipeline else []
            if len(vals_a) < 2 or len(vals_b) < 2:
                missing.append('strike_cov_variance')
            else:
                def _variance(xs: list[float]) -> float:
                    if not xs:
                        return 0.0
                    m = sum(xs)/len(xs)
                    return sum((x-m)**2 for x in xs)/len(xs)
                var_a: float = _variance(vals_a)
                var_b: float = _variance(vals_b)
                # Normalized variance diff: diff = |var_a - var_b| / max(var_a, eps)
                eps = 1e-9 if var_a == 0 else var_a
                var_diff = abs(var_a - var_b) / max(eps, 1e-9)
                var_diff = min(var_diff, 1.0)  # cap
                comp_var = 1 - var_diff
                components['strike_cov_variance'] = comp_var
                details['strike_cov_variance'] = {
                    'variance_a': round(var_a, 6),
                    'variance_b': round(var_b, 6),
                    'diff_norm': round(var_diff, 6),
                    'count_a': len(vals_a),
                    'count_b': len(vals_b),
                }
        except Exception:
            missing.append('strike_cov_variance')

    # Assign weights if not provided (allow explicit override for strike_shape)
    if not weights:
        if components:
            w_each: float = 1.0 / len(components)
            weights = {k: float(w_each) for k in components}
        else:
            weights = {}
    # Optional explicit weight override env (comma list comp:weight)
    try:
        override_raw = os.getenv('G6_PARITY_COMPONENT_WEIGHTS','')
        if override_raw:
            for part in override_raw.split(','):
                if ':' not in part:
                    continue
                k, v = part.split(':',1)
                k = k.strip(); v = v.strip()
                if not k:
                    continue
                try:
                    fv = float(v)
                except Exception:
                    continue
                if k in components:
                    weights[k] = fv
            # Re-normalize weights to sum 1 to keep score bounded
            totw = sum(weights.values()) or 1.0
            for k in list(weights.keys()):
                weights[k] = weights[k] / totw
    except Exception:
        pass

    # Weighted score
    # Defensive copy to ensure weights values are floats (avoid accidental str injection)
    weights = {str(k): float(v) for k, v in weights.items()}
    score: float = 0.0
    for _comp_key, comp_val in components.items():
        w_val = weights.get(_comp_key, 0.0)
        score += float(comp_val) * float(w_val)

    return {
        'version': version,
        'score': round(score, 6),
        'components': components,
        'weights': weights,
        'missing': missing,
        'details': details,
    }

# Rolling parity aggregation (Wave 3)
_ROLLING_SCORES: deque[float] = deque()
_ROLLING_MAXLEN: int = 0

class RollingParityResult(TypedDict):
    avg: float | None
    count: int
    window: int

def record_parity_score(value: float | None) -> RollingParityResult:
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
    if value is not None:
        _ROLLING_SCORES.append(value)
    if not _ROLLING_SCORES:
        return {'avg': None, 'count': 0, 'window': window}
    avg = sum(_ROLLING_SCORES)/len(_ROLLING_SCORES)
    return {'avg': float(avg), 'count': len(_ROLLING_SCORES), 'window': window}

# Backward compatibility: expose simple accessor for rolling average
def get_parity_average() -> float | None:
    if not _ROLLING_SCORES:
        return None
    try:
        return float(sum(_ROLLING_SCORES)/len(_ROLLING_SCORES))
    except Exception:
        return None
