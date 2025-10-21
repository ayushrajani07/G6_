"""Shadow Dual-Run Comparator (Phase 10)

Provides utilities to execute legacy unified collectors and the staged pipeline
in a single process cycle (shadow mode) and compute structured diffs.

Diff Dimensions (initial):
  - counts: indices_processed, snapshot_summary scalar fields (when present)
  - alerts: presence & value equality of alert_* fields
  - coverage: strike_coverage_avg / field_coverage_avg per index
  - partial_reason_totals: per-key counts
  - structural: missing / extra top-level keys in snapshot_summary

Returned Shape:
{
  'mode': 'shadow',
  'legacy': <legacy_result_shallow>,
  'pipeline': <pipeline_result_shallow>,
  'diff': {
     'counts': [...],            # list of dicts describing mismatches
     'alerts': [...],
     'coverage': [...],
     'partial_reason_totals': [...],
     'structural': [...],
     'severity': 'ok'|'warn'|'critical'
  }
}

Severity Heuristics (v1):
  - critical: any structural diff OR >5% drift in indices_processed OR alert mismatch on index_failure / index_empty
  - warn: any other mismatch set
  - ok: no diffs lists populated

The comparator intentionally performs *shallow* comparisons and does not hash
full option chains to keep overhead minimal. Deep parity remains the responsibility
of the dedicated parity harness.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_SHADOW_PERCENT_TOL = 0.05  # 5% tolerance for count drift

_COUNT_KEYS = [
  'indices_processed','snapshot_count'
]
_ALERT_PREFIX = 'alert_'
_COVERAGE_KEYS = ['strike_coverage_avg','field_coverage_avg']


def _shallow_extract(result: dict[str, Any]) -> dict[str, Any]:
  """Extract only fields needed for diff to reduce memory churn."""
  out = {
    k: result.get(k) for k in (
      'status','indices_processed','snapshot_count','snapshot_summary','partial_reason_totals','indices'
    ) if k in result
  }
  # Trim indices to summary coverage subset only
  idx_summaries = []
  for idx in result.get('indices', []) or []:
    idx_summaries.append({
      'index': idx.get('index'),
      'strike_coverage_avg': idx.get('strike_coverage_avg'),
      'field_coverage_avg': idx.get('field_coverage_avg'),
      'option_count': idx.get('option_count'),
    })
  out['indices'] = idx_summaries
  return out


def _percent_drift(a: Any, b: Any) -> float | None:
  try:
    if a is None or b is None:
      return None
    a_f = float(a); b_f = float(b)
    if a_f == b_f == 0:
      return 0.0
    base = max(1.0, a_f)
    return abs(a_f - b_f)/base
  except Exception:
    return None


def _compare_counts(legacy: dict[str, Any], pipeline: dict[str, Any]) -> list[dict[str, Any]]:
  diffs: list[dict[str, Any]] = []
  for key in _COUNT_KEYS:
    la = legacy.get(key); pb = pipeline.get(key)
    if la == pb:
      continue
    drift = _percent_drift(la, pb)
    if drift is None:
      diffs.append({'key': key, 'legacy': la, 'pipeline': pb, 'reason': 'incomparable'})
    elif drift > _SHADOW_PERCENT_TOL:
      diffs.append({'key': key, 'legacy': la, 'pipeline': pb, 'drift': drift})
  # snapshot_summary scalar examples: expiries_total, indices_ok, indices_empty
  for sk in ('expiries_total','indices_ok','indices_empty'):
    lsum = (legacy.get('snapshot_summary') or {}).get(sk)
    psum = (pipeline.get('snapshot_summary') or {}).get(sk)
    if lsum == psum:
      continue
    drift = _percent_drift(lsum, psum)
    if drift is None or drift > _SHADOW_PERCENT_TOL:
      diffs.append({'key': f'snapshot_summary.{sk}', 'legacy': lsum, 'pipeline': psum, 'drift': drift})
  return diffs


def _compare_alerts(legacy: dict[str, Any], pipeline: dict[str, Any]) -> list[dict[str, Any]]:
  out: list[dict[str, Any]] = []
  ls = legacy.get('snapshot_summary') or {}
  ps = pipeline.get('snapshot_summary') or {}
  legacy_alerts = {k:v for k,v in ls.items() if k.startswith(_ALERT_PREFIX)}
  pipe_alerts = {k:v for k,v in ps.items() if k.startswith(_ALERT_PREFIX)}
  keys = set(legacy_alerts) | set(pipe_alerts)
  for k in sorted(keys):
    lv = legacy_alerts.get(k); pv = pipe_alerts.get(k)
    if lv != pv:
      out.append({'alert': k, 'legacy': lv, 'pipeline': pv})
  return out


def _compare_coverage(legacy: dict[str, Any], pipeline: dict[str, Any]) -> list[dict[str, Any]]:
  diffs: list[dict[str, Any]] = []
  lidx = {i.get('index'): i for i in legacy.get('indices', [])}
  pidx = {i.get('index'): i for i in pipeline.get('indices', [])}
  for key in sorted(set(lidx) | set(pidx)):
    li = lidx.get(key); pi = pidx.get(key)
    if not li or not pi:
      diffs.append({'index': key, 'reason': 'missing_in_one'})
      continue
    for cov_key in _COVERAGE_KEYS:
      lv = li.get(cov_key); pv = pi.get(cov_key)
      if lv == pv:
        continue
      diffs.append({'index': key, 'field': cov_key, 'legacy': lv, 'pipeline': pv})
  return diffs


def _compare_partial_reason_totals(legacy: dict[str, Any], pipeline: dict[str, Any]) -> list[dict[str, Any]]:
  lpr = legacy.get('partial_reason_totals') or {}
  ppr = pipeline.get('partial_reason_totals') or {}
  diffs = []
  keys = set(lpr) | set(ppr)
  for k in sorted(keys):
    lv = lpr.get(k, 0); pv = ppr.get(k, 0)
    if lv != pv:
      diffs.append({'partial_reason': k, 'legacy': lv, 'pipeline': pv})
  return diffs


def _compare_structural(legacy: dict[str, Any], pipeline: dict[str, Any]) -> list[dict[str, Any]]:
  lsum = set((legacy.get('snapshot_summary') or {}).keys())
  psum = set((pipeline.get('snapshot_summary') or {}).keys())
  miss = lsum - psum
  extra = psum - lsum
  diffs: list[dict[str, Any]] = []
  for k in sorted(miss):
    diffs.append({'key': k, 'reason': 'missing_in_pipeline'})
  for k in sorted(extra):
    diffs.append({'key': k, 'reason': 'extra_in_pipeline'})
  return diffs


def compute_shadow_diff(legacy_result: dict[str, Any], pipeline_result: dict[str, Any]) -> dict[str, Any]:
  l = _shallow_extract(legacy_result)
  p = _shallow_extract(pipeline_result)
  counts = _compare_counts(l, p)
  alerts = _compare_alerts(l, p)
  coverage = _compare_coverage(l, p)
  partials = _compare_partial_reason_totals(l, p)
  structural = _compare_structural(l, p)
  severity = 'ok'
  if structural or any(d for d in alerts if d.get('alert') in ('alert_index_failure','alert_index_empty')):
    severity = 'critical'
  elif counts or alerts or coverage or partials:
    severity = 'warn'
  return {
    'counts': counts,
    'alerts': alerts,
    'coverage': coverage,
    'partial_reason_totals': partials,
    'structural': structural,
    'severity': severity,
  }

__all__ = ['compute_shadow_diff']
