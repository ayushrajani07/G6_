"""Anomaly detection helpers for benchmark artifacts (B11).

We use robust statistics (Median & Median Absolute Deviation) to flag outliers.
Approach:
 1. Given a numeric series, compute median (m) and MAD = median(|x - m|).
 2. Convert MAD to a robust sigma estimate: sigma ~= 1.4826 * MAD (for normal distribution).
 3. Robust z-score: z = (x - m) / sigma_robust (guarding zero division).
 4. Flag anomalies where |z| >= threshold (default 3.5).

Functions keep dependencies minimal (stdlib only) and return both flags and scores.

Public API:
 - detect_anomalies(series, threshold=3.5, min_points=5) -> (flags, scores)
 - summarize_anomalies(flags, scores) -> count, max_severity
 - rolling_detect(series, window=50, **kwargs) -> list[bool] (flag current using history before it)

All NaN / None values are skipped (not flagged). If insufficient points (< min_points), returns all False.
"""
from __future__ import annotations

import math
from collections.abc import Iterable

__all__ = [
    'detect_anomalies',
    'rolling_detect',
    'summarize_anomalies',
]

_SENTINEL_NAN = float('nan')


def _clean(series: Iterable[float]):
    out = []
    for v in series:
        if v is None:
            continue
        try:
            f = float(v)
        except Exception:
            continue
        if math.isnan(f) or math.isinf(f):
            continue
        out.append(f)
    return out


def detect_anomalies(series: Iterable[float], threshold: float = 3.5, min_points: int = 5) -> tuple[list[bool], list[float]]:
    vals = list(series)
    cleaned = _clean(vals)
    if len(cleaned) < min_points:
        return [False] * len(vals), [0.0] * len(vals)
    # Compute median
    sorted_vals = sorted(cleaned)
    n = len(sorted_vals)
    mid = n // 2
    if n % 2:
        median = sorted_vals[mid]
    else:
        median = 0.5 * (sorted_vals[mid-1] + sorted_vals[mid])
    # MAD
    deviations = [abs(x - median) for x in cleaned]
    deviations_sorted = sorted(deviations)
    mid2 = len(deviations_sorted) // 2
    if len(deviations_sorted) % 2:
        mad = deviations_sorted[mid2]
    else:
        mad = 0.5 * (deviations_sorted[mid2-1] + deviations_sorted[mid2])
    if mad == 0:
        # If deviations are all zero except possibly some outliers, flag any value != median
        flags = []
        scores = []
        for raw in vals:
            try:
                f = float(raw)
            except Exception:
                flags.append(False); scores.append(0.0); continue
            if math.isnan(f) or math.isinf(f):
                flags.append(False); scores.append(0.0); continue
            if f == median:
                flags.append(False); scores.append(0.0)
            else:
                flags.append(True); scores.append(float('inf'))
        return flags, scores
    sigma = 1.4826 * mad
    flags: list[bool] = []
    scores: list[float] = []
    for raw in vals:
        if raw is None:
            flags.append(False); scores.append(0.0); continue
        try:
            f = float(raw)
        except Exception:
            flags.append(False); scores.append(0.0); continue
        if math.isnan(f) or math.isinf(f):
            flags.append(False); scores.append(0.0); continue
        z = (f - median) / sigma if sigma else 0.0
        flags.append(abs(z) >= threshold)
        scores.append(z)
    return flags, scores


def summarize_anomalies(flags: list[bool], scores: list[float]):
    count = sum(1 for f in flags if f)
    max_sev = 0.0
    for f, s in zip(flags, scores, strict=False):
        if f:
            max_sev = max(max_sev, abs(s))
    return {'count': count, 'max_severity': max_sev}


def rolling_detect(series: Iterable[float], window: int = 50, threshold: float = 3.5, min_points: int = 5) -> list[bool]:
    vals = list(series)
    out: list[bool] = []
    for i in range(len(vals)):
        hist = vals[max(0, i-window):i]
        # Enough clean historical points (excluding current) required
        clean_hist = [v for v in hist if v is not None]
        # We consider anomaly once we have enough total samples including current
        if (len(clean_hist) + 1) >= min_points:
            # Compute robust stats on history only
            cleaned = _clean(clean_hist)
            sorted_vals = sorted(cleaned)
            n = len(sorted_vals)
            mid = n // 2
            if n % 2:
                median = sorted_vals[mid]
            else:
                median = 0.5 * (sorted_vals[mid-1] + sorted_vals[mid])
            deviations = [abs(x - median) for x in cleaned]
            deviations_sorted = sorted(deviations)
            mid2 = len(deviations_sorted) // 2
            if len(deviations_sorted) % 2:
                mad = deviations_sorted[mid2]
            else:
                mad = 0.5 * (deviations_sorted[mid2-1] + deviations_sorted[mid2])
            if mad == 0:
                out.append(False)
                continue
            sigma = 1.4826 * mad
            try:
                cur = float(vals[i])
            except Exception:
                out.append(False); continue
            if math.isnan(cur) or math.isinf(cur):
                out.append(False); continue
            z = (cur - median) / sigma if sigma else 0.0
            out.append(abs(z) >= threshold)
        else:
            out.append(False)
    return out
