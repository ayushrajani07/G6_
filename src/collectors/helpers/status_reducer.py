"""Status reduction helpers for per-expiry and cycle-level classification.

Definitions:
  EXPIRY STATUS
    OK      : options > 0 AND strike & field coverage above thresholds AND not synthetic fallback.
    SYNTH   : synthetic_fallback True AND options > 0.
    PARTIAL : options > 0 but coverage below thresholds (strike or field) OR missing key fields.
    EMPTY   : options == 0 (after all fallbacks).

  CYCLE STATUS (aggregated over expiries for an index):
    OK      : >=1 expiry OK and no EMPTY expiries with attempts unless all are OK/SYNTH.
    PARTIAL : Mixed statuses where at least one OK/SYNTH but one or more PARTIAL/EMPTY.
    EMPTY   : All expiries EMPTY.

Thresholds are conservative initial defaults; tune later.
"""
from __future__ import annotations
from typing import Dict, Any, List, Tuple
import os

# Default thresholds (can be overridden via environment variables)
STRIKE_COVERAGE_OK = 0.75  # 75% of requested strikes realized
FIELD_COVERAGE_OK = 0.55   # 55% options with full (volume+oi+avg_price)

ENV_STRIKE = "G6_STRIKE_COVERAGE_OK"
ENV_FIELD = "G6_FIELD_COVERAGE_OK"

def get_status_thresholds() -> Tuple[float, float]:
    """Return (strike_threshold, field_threshold) applying env overrides if present.

    Environment variables:
      G6_STRIKE_COVERAGE_OK : float in [0,1]
      G6_FIELD_COVERAGE_OK  : float in [0,1]

    Invalid / out-of-range values are ignored with a best-effort parse.
    """
    strike_thr = STRIKE_COVERAGE_OK
    field_thr = FIELD_COVERAGE_OK
    s_env = os.getenv(ENV_STRIKE)
    f_env = os.getenv(ENV_FIELD)
    def _parse(v: str | None) -> float | None:
        if v is None:
            return None
        try:
            fv = float(v)
            if 0 <= fv <= 1:
                return fv
        except ValueError:
            return None
        return None
    s_parsed = _parse(s_env)
    f_parsed = _parse(f_env)
    if s_parsed is not None:
        strike_thr = s_parsed
    if f_parsed is not None:
        field_thr = f_parsed
    return strike_thr, field_thr

def compute_expiry_status(expiry_rec: Dict[str, Any]) -> str:
    opts = int(expiry_rec.get('options') or 0)
    if opts == 0:
        return 'EMPTY'
    if expiry_rec.get('synthetic_fallback'):
        return 'SYNTH'
    strike_cov = float(expiry_rec.get('strike_coverage', -1))
    field_cov = float(expiry_rec.get('field_coverage', -1))
    if strike_cov >= 0 and field_cov >= 0:
        strike_thr, field_thr = get_status_thresholds()
        if strike_cov >= strike_thr and field_cov >= field_thr:
            return 'OK'
        return 'PARTIAL'
    # Fallback to existing status if coverage not captured
    return expiry_rec.get('status') or ('OK' if opts>0 else 'EMPTY')

def derive_partial_reason(expiry_rec: Dict[str, Any]) -> str | None:
    """Return a machine-friendly reason token when an expiry is PARTIAL.

    Tokens:
      low_strike  : strike coverage below threshold, field coverage OK
      low_field   : field coverage below threshold, strike coverage OK
      low_both    : both below thresholds
      unknown     : PARTIAL but insufficient coverage metrics to classify
    Returns None if not PARTIAL.
    """
    status = expiry_rec.get('status') or compute_expiry_status(expiry_rec)
    if status != 'PARTIAL':
        return None
    try:
        strike_cov = float(expiry_rec.get('strike_coverage', -1))
        field_cov = float(expiry_rec.get('field_coverage', -1))
        if strike_cov < 0 or field_cov < 0:
            return 'unknown'
        strike_thr, field_thr = get_status_thresholds()
        strike_bad = strike_cov < strike_thr
        field_bad = field_cov < field_thr
        if strike_bad and field_bad:
            return 'low_both'
        if strike_bad:
            return 'low_strike'
        if field_bad:
            return 'low_field'
    except Exception:
        return 'unknown'
    return 'unknown'

def aggregate_cycle_status(expiry_recs: List[Dict[str, Any]]) -> str:
    if not expiry_recs:
        return 'EMPTY'
    statuses = [r.get('status') or compute_expiry_status(r) for r in expiry_recs]
    if all(s == 'EMPTY' for s in statuses):
        return 'EMPTY'
    if all(s in ('OK','SYNTH') for s in statuses):
        return 'OK'
    return 'PARTIAL'

__all__ = ["compute_expiry_status", "aggregate_cycle_status", "get_status_thresholds", "derive_partial_reason", "STRIKE_COVERAGE_OK", "FIELD_COVERAGE_OK"]
