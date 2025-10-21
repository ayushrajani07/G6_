"""Expiry rule token resolution helpers.

Updated 2025-09-30 (per latest exchange schedule provided):
    * Weekly expiries: ONLY NIFTY (Tuesday) & SENSEX (Thursday) currently have weekly contracts.
        BANKNIFTY, FINNIFTY and others in the provided table have NO weekly expiry (treat
        `this_week` / `next_week` as unsupported => return None so caller falls back to
        legacy placeholder coercion if such tokens are still present in config).
    * Monthly expiries: last Tuesday of each month for indices except SENSEX & BANKEX which
        use last Thursday. (Table excerpt: NIFTY, BANKNIFTY, MIDCPNIFTY, FINNIFTY monthly = last Tuesday;
        SENSEX, BANKEX monthly = last Thursday.)

We therefore distinguish WEEKLY and MONTHLY weekday mappings. If a symbol lacks a weekly
mapping, weekly tokens resolve to None. Monthly tokens always attempt resolution using
MONTHLY_EXPIRY_WEEKDAY mapping (falls back to weekly mapping if a monthly mapping entry
is not provided, preserving earlier behavior for symbols not in the new table).

Environment gate: `G6_EXPIRY_RULE_RESOLUTION` (handled by config.validation caller).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

# Weekday mapping per index symbol (Mon=0 .. Sun=6)
# Weekly contracts (current schedule): NIFTY Tuesday (1), SENSEX Thursday (3)
WEEKLY_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 1,    # Tuesday weekly
    "SENSEX": 3,   # Thursday weekly
}

# Monthly contracts mapping (last weekday of month)
# NIFTY, BANKNIFTY, MIDCPNIFTY, FINNIFTY -> last Tuesday (1)
# SENSEX, BANKEX -> last Thursday (3)
MONTHLY_EXPIRY_WEEKDAY: dict[str, int] = {
    "NIFTY": 1,
    "BANKNIFTY": 1,
    "MIDCPNIFTY": 1,
    "FINNIFTY": 1,
    "SENSEX": 3,
    "BANKEX": 3,
}

def _next_weekday_on_or_after(d: date, weekday: int) -> date:
    offset = (weekday - d.weekday()) % 7
    return d + timedelta(days=offset or 0)

def _last_weekday_of_month(year: int, month: int, weekday: int) -> date:
    last_day = monthrange(year, month)[1]
    d = date(year, month, last_day)
    while d.weekday() != weekday:
        d -= timedelta(days=1)
    return d

def resolve_rule(symbol: str, token: str, today: date | None = None) -> str | None:
    """Resolve a rule token to ISO date or return None if unsupported.

    Rules:
      this_week  -> upcoming (on or after today) weekly expiry weekday
      next_week  -> weekly expiry + 7 days
      this_month -> last weekly-expiry weekday of current month
      next_month -> last weekly-expiry weekday of next month
    """
    if today is None:
        today = date.today()
    sym = symbol.upper()
    t = token.lower()
    try:
        if t in {"this_week", "next_week"}:
            w_weekday = WEEKLY_EXPIRY_WEEKDAY.get(sym)
            if w_weekday is None:
                return None  # Symbol has no weekly contract
            if t == "this_week":
                resolved = _next_weekday_on_or_after(today, w_weekday)
            else:  # next_week
                base = _next_weekday_on_or_after(today, w_weekday)
                resolved = base + timedelta(days=7)
        elif t in {"this_month", "next_month"}:
            m_weekday = MONTHLY_EXPIRY_WEEKDAY.get(sym) or WEEKLY_EXPIRY_WEEKDAY.get(sym)
            if m_weekday is None:
                return None
            if t == "this_month":
                resolved = _last_weekday_of_month(today.year, today.month, m_weekday)
            else:  # next_month
                if today.month == 12:
                    ny, nm = today.year + 1, 1
                else:
                    ny, nm = today.year, today.month + 1
                resolved = _last_weekday_of_month(ny, nm, m_weekday)
        else:
            return None
        return resolved.isoformat()
    except Exception:  # pragma: no cover - defensive
        return None

__all__ = ["resolve_rule"]
