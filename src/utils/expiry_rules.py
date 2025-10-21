"""Shared expiry rule selection utilities.

Implements list-based expiry selection without weekday assumptions.

Rules:
- this_week: closest future expiry (min date >= today)
- next_week: second closest future expiry, or closest if only one
- this_month: last available expiry within today's month; fallback to closest
- next_month: last available expiry within next month; fallback to second closest else closest

All functions are pure and easy to unit test.
"""
from __future__ import annotations

import datetime as _dt
from collections.abc import Iterable


def normalize_rule(rule: str) -> str:
    r = (rule or '').strip().lower().replace('-', '_')
    if r in {"current_week"}:
        r = "this_week"
    if r in {"following_week"}:
        r = "next_week"
    if r in {"current_month"}:
        r = "this_month"
    if r in {"following_month"}:
        r = "next_month"
    return r


def select_expiry(expiries_iter: Iterable[_dt.date], rule: str, *, today: _dt.date | None = None) -> _dt.date:
    """Return an expiry date from a list using the normalized list-based rules.

    Args:
        expiries_iter: Iterable of candidate expiry dates (any order)
        rule: Expiry rule (this_week, next_week, this_month, next_month)
        today: Reference date (defaults to date.today())

    Raises:
        ValueError: If there are no valid future expiries
    """
    today = today or _dt.date.today()
    # Filter to dates >= today and sort ascending
    expiries: list[_dt.date] = sorted(d for d in expiries_iter if isinstance(d, _dt.date) and d >= today)
    if not expiries:
        raise ValueError("no future expiries available")

    r = normalize_rule(rule)

    def last_in_month(year: int, month: int) -> _dt.date | None:
        cands = [d for d in expiries if d.year == year and d.month == month]
        return max(cands) if cands else None

    if r == 'this_week':
        return expiries[0]
    if r == 'next_week':
        return expiries[1] if len(expiries) >= 2 else expiries[0]
    if r == 'this_month':
        dt = last_in_month(today.year, today.month)
        return dt if dt else expiries[0]
    if r == 'next_month':
        nm_year = today.year + (1 if today.month == 12 else 0)
        nm_month = 1 if today.month == 12 else (today.month + 1)
        dt = last_in_month(nm_year, nm_month)
        if dt:
            return dt
        return expiries[1] if len(expiries) >= 2 else expiries[0]

    # Unknown rule -> closest
    return expiries[0]


__all__ = [
    "normalize_rule",
    "select_expiry",
]
