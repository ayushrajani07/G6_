"""Phase 9: Alert Aggregation Core

Derives structured alert counts from per-index + per-expiry records built by
collectors (pipeline or legacy) without additional provider calls.

Counting Policy (v1):
  * Coverage, empties, synthetic usage counted per-expiry occurrence.
  * Index-level failures/empties counted once per index (even if multiple expiries). 
  * Coverage thresholds configurable via env or parameters.

Environment Overrides:
  G6_ALERT_STRIKE_COV_MIN (default 0.6)
  G6_ALERT_FIELD_COV_MIN  (default 0.5)

Returned Structure (dict via AlertSummary.to_dict):
  {
    'alerts_total': int,
    'alerts': {category: count, ...},
    'alerts_index_triggers': {category: [indices...]}
  }

Categories:
  index_failure
  index_empty
  expiry_empty
  low_strike_coverage
  low_field_coverage
  low_both_coverage
  synthetic_quotes_used
  (Future placeholders - anomaly_detected, validation_issues, degraded_provider_mode)

Future Enhancements:
  * Severity levels (warning/critical)
  * Rate limiting noisy categories
  * Parity harness extension of flattened metrics
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Set
import os

__all__ = ["aggregate_alerts", "AlertSummary"]


@dataclass
class AlertSummary:
    total: int
    categories: Dict[str, int]
    index_triggers: Dict[str, List[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            'alerts_total': self.total,
            'alerts': dict(self.categories),
            'alerts_index_triggers': {k: v[:] for k, v in self.index_triggers.items()},
        }


def _env_float(name: str, default: float) -> float:
    try:
        val = float(os.environ.get(name, default))
        return val
    except Exception:
        return default


def aggregate_alerts(indices_struct: List[Dict[str, Any]], *, strike_cov_min: float | None = None, field_cov_min: float | None = None) -> AlertSummary:
    strike_min = strike_cov_min if strike_cov_min is not None else _env_float('G6_ALERT_STRIKE_COV_MIN', 0.6)
    field_min = field_cov_min if field_cov_min is not None else _env_float('G6_ALERT_FIELD_COV_MIN', 0.5)

    counts: Dict[str, int] = {
        'index_failure': 0,
        'index_empty': 0,
        'expiry_empty': 0,
        'low_strike_coverage': 0,
        'low_field_coverage': 0,
        'low_both_coverage': 0,
        'synthetic_quotes_used': 0,
          # Phase 10 taxonomy expansion (optional; gated by env thresholds)
          'liquidity_low': 0,
          'stale_quote': 0,
          'wide_spread': 0,
    }
    triggers: Dict[str, Set[str]] = {k: set() for k in counts.keys()}

    for idx in indices_struct:
        index_symbol = idx.get('index') or 'UNKNOWN'
        failures = int(idx.get('failures') or 0)
        status = (idx.get('status') or '').upper()
        expiries = idx.get('expiries') or []

        if failures > 0:
            counts['index_failure'] += 1
            triggers['index_failure'].add(index_symbol)
        if status == 'EMPTY':
            counts['index_empty'] += 1
            triggers['index_empty'].add(index_symbol)
        # Thresholds for new taxonomy (env or defaults)
        try:
            liq_min_ratio = float(os.environ.get('G6_ALERT_LIQUIDITY_MIN_RATIO', '0.05'))  # volume/oi or volume/notional heuristic
        except Exception:
            liq_min_ratio = 0.05
        try:
            stale_age_s = float(os.environ.get('G6_ALERT_QUOTE_STALE_AGE_S', '45'))  # seconds since last trade/quote
        except Exception:
            stale_age_s = 45.0
        try:
            spread_pct_max = float(os.environ.get('G6_ALERT_WIDE_SPREAD_PCT', '5'))  # percent
        except Exception:
            spread_pct_max = 5.0
        enable_extended = os.environ.get('G6_ALERT_TAXONOMY_EXTENDED','').lower() in ('1','true','yes','on')

        for exp in expiries:
            if not isinstance(exp, dict):
                continue
            exp_status = (exp.get('status') or '').upper()
            if exp_status == 'EMPTY':
                counts['expiry_empty'] += 1
                triggers['expiry_empty'].add(index_symbol)
            s_cov = exp.get('strike_coverage')
            f_cov = exp.get('field_coverage')
            low_strike = isinstance(s_cov, (int, float)) and s_cov < strike_min
            low_field = isinstance(f_cov, (int, float)) and f_cov < field_min
            if low_strike:
                counts['low_strike_coverage'] += 1
                triggers['low_strike_coverage'].add(index_symbol)
            if low_field:
                counts['low_field_coverage'] += 1
                triggers['low_field_coverage'].add(index_symbol)
            if low_strike and low_field:
                counts['low_both_coverage'] += 1
                triggers['low_both_coverage'].add(index_symbol)
            if exp.get('synthetic_quotes'):
                counts['synthetic_quotes_used'] += 1
                triggers['synthetic_quotes_used'].add(index_symbol)
            # Extended taxonomy evaluation (per-expiry aggregate heuristics)
            if enable_extended:
                try:
                    meta = exp  # expiry record may carry aggregate fields
                    # liquidity_low: check ratio of avg volume to option_count heuristic
                    avg_vol = meta.get('avg_volume') or meta.get('avg_traded_volume')
                    opt_cnt = meta.get('options') or 0
                    if isinstance(avg_vol, (int,float)) and opt_cnt and opt_cnt>0:
                        ratio = (avg_vol / opt_cnt) if opt_cnt else 0
                        if ratio < liq_min_ratio:
                            counts['liquidity_low'] += 1
                            triggers['liquidity_low'].add(index_symbol)
                    # stale_quote: if last_quote_age_s field present and exceeds threshold
                    age_s = meta.get('last_quote_age_s') or meta.get('max_quote_age_s')
                    if isinstance(age_s, (int,float)) and age_s > stale_age_s:
                        counts['stale_quote'] += 1
                        triggers['stale_quote'].add(index_symbol)
                    # wide_spread: check avg_spread_pct field
                    spread_pct = meta.get('avg_spread_pct') or meta.get('mean_spread_pct')
                    if isinstance(spread_pct, (int,float)) and spread_pct > spread_pct_max:
                        counts['wide_spread'] += 1
                        triggers['wide_spread'].add(index_symbol)
                except Exception:
                    pass

    total = sum(counts.values())
    return AlertSummary(total=total, categories=counts, index_triggers={k: sorted(v) for k, v in triggers.items() if v})
