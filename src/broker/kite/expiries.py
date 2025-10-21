"""Expiry discovery and resolution helpers (Phase 1 extraction).

These functions are thin extractions from the original kite_provider module to
reduce size and prepare for further modularization. Behavior must remain
IDENTICAL to pre-refactor semantics.
"""
from __future__ import annotations

import datetime as _dt
import logging

logger = logging.getLogger(__name__)

# The provider instance passed in is expected to offer:
#   - get_expiry_dates(self, index_symbol: str) -> list[date]
#     (For real provider this will still be the large method until Phase 2/3)
# During Phase 1 we only extract the resolution logic; the heavy discovery
# function stays in place so resolve_expiry can delegate here.


def resolve_expiry_rule(provider, index_symbol: str, expiry_rule: str):
    """Resolve an expiry rule into a concrete date using provider's expiry list.

    Rules (unchanged):
      this_week  -> nearest future expiry
      next_week  -> 2nd nearest future expiry (fallback nearest)
      this_month -> nearest monthly anchor (first per-month last expiry)
      next_month -> 2nd monthly anchor (fallback first)

    On error, returns today's date (defensive parity with original).
    """
    try:
        today = _dt.date.today()
        expiries = sorted(d for d in provider.get_expiry_dates(index_symbol) if isinstance(d, _dt.date) and d >= today)
        if not expiries:
            return today
        nearest = expiries[0]
        second = expiries[1] if len(expiries) > 1 else nearest
        # Monthly anchors: last expiry per month
        month_last = {}
        for d in expiries:
            month_last[(d.year, d.month)] = d
        monthly_sorted: list[_dt.date] = sorted(month_last.values())
        this_month_date = monthly_sorted[0]
        next_month_date = monthly_sorted[1] if len(monthly_sorted) > 1 else this_month_date
        rule = (expiry_rule or '').lower()
        if rule == 'this_week':
            chosen = nearest
        elif rule == 'next_week':
            chosen = second
        elif rule == 'this_month':
            chosen = this_month_date
        elif rule == 'next_month':
            chosen = next_month_date
        else:
            chosen = nearest
        # Mirror concise vs verbose behavior: keep debug-level emission (caller still decides concise mode outside)
        logger.debug("Resolved '%s' for %s -> %s", expiry_rule, index_symbol, chosen)
        return chosen
    except Exception:  # pragma: no cover - defensive catch identical to legacy fallback
        return _dt.date.today()
