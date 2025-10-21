"""Expiry Service
=================

Centralizes expiry date selection and classification logic that is currently
scattered across providers, ad-hoc helper functions, and preventive validators.

Goals:
 - Deterministic selection of weekly / next-week / monthly / next-month expiries.
 - Ability to plug in an exchange holiday calendar to skip non-trading days.
 - Clear classification helpers (is_weekly_expiry, is_monthly_expiry).
 - Normalized interface returning `date` objects only (never strings) with
   guaranteed forward-only (>= today) semantics unless explicitly overridden.
 - Lightweight and dependency-free; calendar/holiday injection performed via
   optional callable passed at construction or per call.

This module intentionally does NOT perform network/API lookups. It operates on
the candidate expiry date list supplied (e.g., from a provider). If the list is
empty or no future expiries remain, a descriptive error is raised.

Integration Plan (incremental):
 1. Introduce service and unit tests (this change).
 2. Replace direct calls to `providers.resolve_expiry` and `select_expiry` in
    collectors / analytics paths behind a feature flag
    (e.g., G6_EXPIRY_SERVICE=1) in subsequent PR.
 3. Later, add optional caching and holiday calendar loader.

Public API (stable draft):
 - ExpiryService(today: date | None = None, holiday_fn: Callable[[date], bool] | None = None)
 - select(rule: str, candidates: Iterable[date]) -> date
 - classify(expiry: date, *, weekly_dow: int = 3, monthly_dow: int = 3) -> dict
 - is_weekly_expiry(expiry: date, *, weekly_dow: int = 3) -> bool
 - is_monthly_expiry(expiry: date, *, monthly_dow: int = 3) -> bool

Rules Supported (mirrors existing list-based semantics):
 - this_week: closest future (>= today) expiry
 - next_week: second closest future expiry (or closest if only one)
 - this_month: last expiry within current month (fallback first future)
 - next_month: last expiry within next month (fallback second future else first)

Edge Cases & Guarantees:
 - If all candidate dates are < today -> ValueError("no future expiries available")
 - Holiday removal performed before rule evaluation; if removal empties list a
   ValueError is raised (surfaced distinctly for easier debugging).
 - Duplicate dates are collapsed.
 - Input order is irrelevant (internally sorted ascending).

Future Extensions (not implemented now):
 - Support for numeric offsets (e.g., +2w, +1m) or explicit YYYY-MM-DD pass-through.
 - Market session aware same-day expiry gating by time of day.
 - Multi-exchange holiday sets per symbol.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date as _date

try:
    from src.collectors.env_adapter import get_bool as _env_get_bool  # type: ignore
    from src.collectors.env_adapter import get_int as _env_get_int
    from src.collectors.env_adapter import get_str as _env_get_str
except Exception:  # pragma: no cover
    # Safe fallbacks if adapter not available
    def _env_get_bool(name: str, default: bool = False) -> bool:
        try:
            v = os.getenv(name)
            if v is None:
                return default
            return str(v).strip().lower() in {"1","true","yes","on","y"}
        except Exception:
            return default
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default
    def _env_get_int(name: str, default: int) -> int:
        try:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return int(str(v).strip())
        except Exception:
            return default

__all__ = [
    "ExpiryService",
    "is_weekly_expiry",
    "is_monthly_expiry",
    "build_expiry_service",
    "load_holiday_calendar",
]


@dataclass(slots=True)
class ExpiryService:
    """High-level expiry selection facade.

    Parameters
    ----------
    today: date | None
        Reference 'today'. If None, resolved dynamically per call (UTC-local
        system interpretation). Fixed 'today' is useful in tests.
    holiday_fn: Callable[[date], bool] | None
        Optional predicate returning True if date is a (full) market holiday and
        should be excluded from candidate consideration.
    weekly_dow: int
        Weekday integer (Mon=0..Sun=6) representing weekly expiry (default 3=Thursday).
    monthly_dow: int
        Weekday integer for monthly expiry anchor (default 3=Thursday) when
        computing last monthly occurrence classification.
    """

    today: _date | None = None
    holiday_fn: Callable[[_date], bool] | None = None
    weekly_dow: int = 3
    monthly_dow: int = 3

    # ---- Core Selection -------------------------------------------------
    def select(self, rule: str, candidates: Iterable[_date]) -> _date:
        """Select an expiry date using a normalized rule.

        Parameters
        ----------
        rule: str
            Selection rule (this_week, next_week, this_month, next_month).
        candidates: Iterable[date]
            Raw candidate expiry dates (may include past dates / duplicates / holidays).

        Returns
        -------
        date
            The selected expiry date.
        """
        normalized_rule = (rule or "").strip().lower()
        if normalized_rule not in {"this_week", "next_week", "this_month", "next_month"}:
            raise ValueError(f"unsupported expiry rule: {rule}")

        today = self.today or _date.today()
        uniq: list[_date] = sorted({d for d in candidates if isinstance(d, _date)})
        # Remove holidays first
        if self.holiday_fn:
            uniq = [d for d in uniq if not self.holiday_fn(d)]
        # Keep only forward dates (>= today)
        future = [d for d in uniq if d >= today]
        if not future:
            raise ValueError("no future expiries available after filtering")

        if normalized_rule == "this_week":
            return future[0]
        if normalized_rule == "next_week":
            return future[1] if len(future) >= 2 else future[0]

        # Month-scoped rules
        if normalized_rule == "this_month":
            year, month = today.year, today.month
            month_scope = [d for d in future if d.year == year and d.month == month]
            if month_scope:
                return month_scope[-1]
            # Fallback (reverted): choose first monthly anchor (last expiry of the next month)
            month_last: dict[tuple[int,int], _date] = {}
            for d in future:
                month_last[(d.year, d.month)] = d
            monthly_anchors = sorted(month_last.values())
            return monthly_anchors[0]

        if normalized_rule == "next_month":
            # Updated semantics: second monthly anchor (second element of ordered month-last list)
            month_last: dict[tuple[int,int], _date] = {}
            for d in future:
                month_last[(d.year, d.month)] = d
            monthly_anchors = sorted(month_last.values())
            if len(monthly_anchors) >= 2:
                return monthly_anchors[1]
            return monthly_anchors[0]

        # Defensive (should not reach)
        raise AssertionError("unreachable rule branch")

    # ---- Classification -------------------------------------------------
    def classify(self, expiry: _date) -> dict[str, bool]:
        """Return classification flags for an expiry."""
        return {
            "is_weekly": is_weekly_expiry(expiry, weekly_dow=self.weekly_dow),
            "is_monthly": is_monthly_expiry(expiry, monthly_dow=self.monthly_dow),
        }


def is_weekly_expiry(expiry: _date, *, weekly_dow: int = 3) -> bool:
    """Return True if the expiry matches the configured weekly expiry weekday.

    Note: This does not validate against a holiday calendar; it is purely a
    weekday structural check.
    """
    return expiry.weekday() == weekly_dow


def is_monthly_expiry(expiry: _date, *, monthly_dow: int = 3) -> bool:
    """Return True if the date is the last occurrence of `monthly_dow` in its month."""
    # Find the next same weekday; if month differs then current is last.
    from datetime import timedelta

    check = expiry
    while True:
        check += timedelta(days=7)
        if check.month != expiry.month:
            # expiry is last occurrence of that weekday in its month
            return expiry.weekday() == monthly_dow


# Convenience for bulk selection (could be used later by collectors)
def select_expiries(service: ExpiryService, rules: Sequence[str], candidates: Iterable[_date]) -> dict[str, _date]:
    """Return mapping of rule -> selected date using a shared candidate list."""
    out: dict[str, _date] = {}
    for r in rules:
        try:
            out[r] = service.select(r, candidates)
        except Exception:  # pragma: no cover - tolerant batch selection
            continue
    return out


# ---- Holiday Calendar Loader & Service Builder ---------------------------
def load_holiday_calendar(path: str | None) -> set[_date]:
    """Load a JSON file containing a list of YYYY-MM-DD strings.

    Returns empty set if path is None, file missing, or parse error occurs. Logs warnings.
    """
    if not path:
        return set()
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
        out: set[_date] = set()
        for item in raw or []:
            if isinstance(item, str) and len(item) == 10:
                try:
                    y, m, d = item.split('-')
                    out.add(_date(int(y), int(m), int(d)))
                except Exception:  # pragma: no cover
                    continue
        logging.info(f"Loaded {len(out)} holidays from {path}")
        return out
    except FileNotFoundError:
        logging.warning(f"Holiday calendar file not found: {path}")
    except Exception as e:  # pragma: no cover
        logging.warning(f"Failed loading holiday calendar {path}: {e}")
    return set()


def build_expiry_service() -> ExpiryService | None:
    """Construct an ExpiryService if G6_EXPIRY_SERVICE=1 else return None.

    Honors optional env variables:
     - G6_EXPIRY_SERVICE: enable flag ("1" / "true")
     - G6_HOLIDAYS_FILE: path to JSON list of holidays
     - G6_WEEKLY_EXPIRY_DOW: override int weekday for weekly expiry
     - G6_MONTHLY_EXPIRY_DOW: override int weekday for monthly expiry anchor
    """
    if not _env_get_bool("G6_EXPIRY_SERVICE", False):
        return None
    hol_path = _env_get_str("G6_HOLIDAYS_FILE", "").strip() or None
    holidays = load_holiday_calendar(hol_path)
    holiday_fn = (lambda d: d in holidays) if holidays else None
    weekly = _env_get_int("G6_WEEKLY_EXPIRY_DOW", 3)
    monthly = _env_get_int("G6_MONTHLY_EXPIRY_DOW", 3)
    svc = ExpiryService(today=None, holiday_fn=holiday_fn, weekly_dow=weekly, monthly_dow=monthly)
    logging.info(
        f"ExpiryService enabled (weekly_dow={weekly} monthly_dow={monthly} holidays={len(holidays) if holidays else 0})"
    )
    return svc
