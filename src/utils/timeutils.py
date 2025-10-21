"""
Time Utilities for G6 Platform
Consolidated time utilities from various modules.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC as _UTC, date, datetime, timedelta
from datetime import time as dt_time
from zoneinfo import ZoneInfo

# Timezones (zoneinfo)
IST = ZoneInfo('Asia/Kolkata')
UTC = _UTC

# Market hours (IST)
MARKET_OPEN = dt_time(9, 15)  # 9:15 AM
MARKET_CLOSE = dt_time(15, 30)  # 3:30 PM

# Pre-market and post-market
PRE_MARKET_START = dt_time(9, 0)   # 9:00 AM
POST_MARKET_END = dt_time(16, 0)   # 4:00 PM

def get_ist_now() -> datetime:
    """Get current time in IST (aware)."""
    return datetime.now(tz=IST)

def get_utc_now() -> datetime:
    """Get current time in UTC (aware)."""
    return datetime.now(tz=UTC)

def utc_now() -> datetime:
    """Return an aware UTC datetime."""
    return datetime.now(tz=UTC)

def isoformat_z(dt: datetime) -> str:
    """Return RFC3339/ISO8601 style string with 'Z' suffix for UTC datetimes.

    If dt is naive it is assumed to already represent UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).isoformat().replace('+00:00','Z')
    return dt.astimezone(UTC).isoformat().replace('+00:00','Z')

def ensure_utc_helpers() -> tuple[Callable[[], datetime], Callable[[datetime], str]]:
    """Return (utc_now_fn, isoformat_z_fn) always available.

    Intended for early bootstrap contexts where importing this module may be
    wrapped in try/except. Provides a consistent interface so callers no
    longer need to duplicate fallback lambdas.
    """
    return utc_now, isoformat_z

def ist_to_utc(ist_dt: datetime) -> datetime:
    """Convert IST datetime to UTC (assumes naive input is IST)."""
    if ist_dt.tzinfo is None:
        ist_dt = ist_dt.replace(tzinfo=IST)
    return ist_dt.astimezone(UTC)

def utc_to_ist(utc_dt: datetime) -> datetime:
    """Convert UTC datetime to IST (assumes naive input is UTC)."""
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=UTC)
    return utc_dt.astimezone(IST)

def _weekend_mode() -> bool:
    """Return True if weekend trading override is enabled.

    Controlled by G6_WEEKEND_MODE (values: 1/true/on/yes). When enabled, weekend
    days (Saturday/Sunday) are treated the same as weekdays for the purposes of
    platform run gating. This is intended for demo / backtesting / continuous
    soak scenarios where collectors should keep cycling on weekends.
    """
    import os
    try:
        v = os.getenv('G6_WEEKEND_MODE', '').strip().lower()
        return v in {'1','true','yes','on'}
    except Exception:
        return False

def is_market_open(check_time: datetime | None = None) -> bool:
    """Check if market is currently open.

    Weekend gating can be disabled via G6_WEEKEND_MODE to allow continuous
    operation with normal intraday hour checks still enforced.
    """
    if check_time is None:
        check_time = get_ist_now()
    elif check_time.tzinfo != IST:
        check_time = check_time.astimezone(IST)

    # Check weekday (Monday=0, Sunday=6)
    if check_time.weekday() >= 5:  # Saturday or Sunday
        return False

    current_time = check_time.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE

def market_hours_check(check_time: datetime | None = None) -> tuple[bool, str]:
    """Detailed market hours check with status message.

    Respects G6_WEEKEND_MODE override: when enabled, weekend days are not
    treated as automatically closed; normal intraday phase classification
    applies instead.
    """
    if check_time is None:
        check_time = get_ist_now()
    elif check_time.tzinfo != IST:
        check_time = check_time.astimezone(IST)

    weekday = check_time.weekday()
    current_time = check_time.time()

    if weekday >= 5 and not _weekend_mode():  # Weekend unless override enabled
        return False, "market_closed_weekend"

    if current_time < PRE_MARKET_START:
        return False, "before_premarket"
    if current_time < MARKET_OPEN:
        return False, "premarket"
    if current_time <= MARKET_CLOSE:
        return True, "market_open"
    if current_time <= POST_MARKET_END:
        return False, "post_market"
    return False, "market_closed"

def next_market_open(from_time: datetime | None = None) -> datetime:
    """Get next market opening time.

    In weekend mode, weekends are not skipped when computing the next open –
    the next open may be later the same day (if before open) or the following
    calendar day regardless of weekday.
    """
    if from_time is None:
        from_time = get_ist_now()
    elif from_time.tzinfo != IST:
        from_time = from_time.astimezone(IST)

    # Start from next day if market is closed today
    check_date = from_time.date()
    if from_time.time() > MARKET_CLOSE or (from_time.weekday() >= 5 and not _weekend_mode()):
        check_date = from_time.date() + timedelta(days=1)

    # Combine with open time for resulting datetime
    return datetime.combine(check_date, MARKET_OPEN, tzinfo=IST)

def time_until_market_open(from_time: datetime | None = None) -> float:
    """Get seconds until market opens."""
    if from_time is None:
        from_time = get_ist_now()

    next_open = next_market_open(from_time)
    return (next_open - from_time).total_seconds()

def format_ist_time(dt: datetime) -> str:
    """Format datetime as IST string."""
    if dt.tzinfo != IST:
        dt = dt.astimezone(IST)
    return dt.strftime("%Y-%m-%d %H:%M:%S IST")

def get_market_session_bounds(trade_date: date | None = None) -> tuple[datetime, datetime]:
    """Get market session start and end times for a date."""
    if trade_date is None:
        trade_date = get_ist_now().date()

    start = datetime.combine(trade_date, MARKET_OPEN, tzinfo=IST)
    end = datetime.combine(trade_date, MARKET_CLOSE, tzinfo=IST)

    return start, end

# Expiry calculation utilities
def _at_ist(d: datetime, hh: int, mm: int) -> datetime:
    """Set time components of a datetime."""
    if d.tzinfo != IST:
        d = d.astimezone(IST)
    return d.replace(hour=hh, minute=mm, second=0, microsecond=0)

def _next_weekday_on_or_after(d: date, target_wd: int) -> date:
    """Find the next occurrence of target weekday on or after date d."""
    days_ahead = (target_wd - d.weekday()) % 7
    return d + timedelta(days=days_ahead)

def _last_weekday_of_month(d: date, target_wd: int) -> date:
    """Find the last occurrence of target weekday in the month of date d."""
    # Go to first day of next month, then step back to last target weekday
    first_of_next = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
    last_day = first_of_next - timedelta(days=1)
    days_back = (last_day.weekday() - target_wd) % 7
    return last_day - timedelta(days=days_back)

def compute_weekly_expiry(now_date: datetime | date, weekly_dow: int = 3) -> date:
    """Compute weekly expiry date (default Thursday)."""
    # Convert to date if datetime
    if isinstance(now_date, datetime):
        check_date = now_date.date()
    else:
        check_date = now_date

    # If today is expiry day (e.g., Thursday) and before cutoff, return today
    # Otherwise return next week
    this_week_expiry = _next_weekday_on_or_after(check_date, weekly_dow)

    if check_date == this_week_expiry:
        # For same-day expiry, would need to check time
        # But we're simplifying here
        return this_week_expiry

    return this_week_expiry

def compute_next_weekly_expiry(now_date: datetime | date, weekly_dow: int = 3) -> date:
    """Compute next weekly expiry after the current one."""
    this_week = compute_weekly_expiry(now_date, weekly_dow)
    return this_week + timedelta(days=7)

def compute_monthly_expiry(now_date: datetime | date, monthly_dow: int = 3) -> date:
    """Compute monthly expiry (last Thursday of month by default)."""
    # Convert to date if datetime
    if isinstance(now_date, datetime):
        check_date = now_date.date()
    else:
        check_date = now_date

    return _last_weekday_of_month(check_date, monthly_dow)

def compute_next_monthly_expiry(now_date: datetime | date, monthly_dow: int = 3) -> date:
    """Compute next month's expiry."""
    # Get first day of next month
    if isinstance(now_date, datetime):
        check_date = now_date.date()
    else:
        check_date = now_date

    next_month = (check_date.replace(day=1) + timedelta(days=32)).replace(day=1)
    return _last_weekday_of_month(next_month, monthly_dow)

# ---------------------------------------------------------------------------
# Generic Timestamp Rounding Utilities
# ---------------------------------------------------------------------------
def round_timestamp(dt: datetime, step_seconds: int = 30, strategy: str = 'nearest') -> datetime:
    """Round a naive or tz-aware datetime to a step boundary.

    Parameters
    ----------
    dt : datetime
        Input datetime (naive interpreted as-is; timezone preserved if present).
    step_seconds : int, default 30
        Granularity in seconds (commonly 30 for existing CSV alignment). Must divide 3600 evenly for predictable behavior.
    strategy : str, default 'nearest'
        One of: 'nearest', 'floor', 'ceil'.

    Returns
    -------
    datetime
        Rounded datetime (microseconds cleared).
    """
    if step_seconds <= 0:
        raise ValueError("step_seconds must be positive")
    # Normalize microseconds early for deterministic math
    base = dt.replace(microsecond=0)
    epoch = base.replace(hour=0, minute=0, second=0)
    seconds_since_midnight = (base - epoch).total_seconds()
    remainder = seconds_since_midnight % step_seconds
    if strategy == 'nearest':
        if remainder < (step_seconds / 2):
            delta = -remainder
        else:
            delta = (step_seconds - remainder)
    elif strategy == 'floor':
        delta = -remainder
    elif strategy == 'ceil':
        delta = (step_seconds - remainder) if remainder > 0 else 0
    else:
        raise ValueError("strategy must be one of 'nearest','floor','ceil'")
    rounded = base + timedelta(seconds=delta)
    return rounded

def format_rounded_timestamp(dt: datetime, step_seconds: int = 30, fmt: str = '%d-%m-%Y %H:%M:%S', strategy: str = 'nearest') -> str:
    """Convenience: round timestamp then format."""
    return round_timestamp(dt, step_seconds=step_seconds, strategy=strategy).strftime(fmt)

# ---------------------------------------------------------------------------
# IST-specific front-end rounding/formatting helpers
# ---------------------------------------------------------------------------
def round_to_30s_ist(dt: datetime, strategy: str = 'nearest') -> datetime:
    """Return dt rounded to the nearest 30s boundary in IST.

    - Preserves timezone awareness and returns an aware datetime in IST.
    - If input is naive, assumes UTC (consistent with project convention) before conversion.
    - Rounds to either :00 or :30 within the minute as requested.
    """
    # Normalize to aware UTC then convert to IST for rounding
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt_ist = dt.astimezone(IST)
    rounded_ist = round_timestamp(dt_ist, step_seconds=30, strategy=strategy)
    # Ensure seconds are exactly 0 or 30 (guard against drift)
    s = rounded_ist.second
    if s not in (0, 30):
        # Snap to nearest of 0 or 30
        snap = 0 if s < 15 or (s >= 45 and strategy != 'floor') else 30
        rounded_ist = rounded_ist.replace(second=snap, microsecond=0)
        # If snapping rolled minute (e.g., ceil), handle via strategy in round_timestamp already
    return rounded_ist


def format_ist_hms_30s(dt: datetime, strategy: str = 'nearest') -> str:
    """Format a datetime as IST HH:MM:SS after 30s rounding.

    Output format strictly HH:MM:SS (e.g., 09:15:00, 09:15:30).
    """
    return round_to_30s_ist(dt, strategy=strategy).strftime('%H:%M:%S')


def format_any_to_ist_hms_30s(ts: datetime | float | int | str, strategy: str = 'nearest') -> str | None:
    """Accept datetime/epoch/ISO and return IST HH:MM:SS with 30s rounding.

    - datetime: used as-is
    - float/int: interpreted as UNIX epoch seconds (UTC)
    - str: parsed as ISO8601; 'Z' suffix supported (UTC)
    Returns None if parsing fails.
    """
    try:
        if isinstance(ts, datetime):
            return format_ist_hms_30s(ts, strategy=strategy)
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(float(ts), tz=UTC)
            return format_ist_hms_30s(dt, strategy=strategy)
        if isinstance(ts, str):
            # Support common ISO forms, allow trailing Z
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return format_ist_hms_30s(dt, strategy=strategy)
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Extended convenience: full date+time formatting (DD-MM-YYYY HH:MM:SS) in IST
# ---------------------------------------------------------------------------
def format_ist_dt_30s(dt: datetime, strategy: str = 'nearest', fmt: str = '%d-%m-%Y %H:%M:%S') -> str:
    """Return full date+time string in IST after 30s rounding.

    Parameters
    ----------
    dt : datetime
        Input datetime (naive assumed UTC).
    strategy : str, default 'nearest'
        Rounding strategy ('nearest','floor','ceil').
    fmt : str, default '%d-%m-%Y %H:%M:%S'
        strftime format applied after rounding (kept consistent with CSV expectations).
    """
    return round_to_30s_ist(dt, strategy=strategy).strftime(fmt)


def format_any_to_ist_dt_30s(ts: datetime | float | int | str, strategy: str = 'nearest', fmt: str = '%d-%m-%Y %H:%M:%S') -> str | None:
    """Accept heterogeneous timestamp input and return IST date+time string (30s rounding).

    Returns None on parse failure.
    """
    try:
        if isinstance(ts, datetime):
            return format_ist_dt_30s(ts, strategy=strategy, fmt=fmt)
        if isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(float(ts), tz=UTC)
            return format_ist_dt_30s(dt, strategy=strategy, fmt=fmt)
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return format_ist_dt_30s(dt, strategy=strategy, fmt=fmt)
    except Exception:  # pragma: no cover - defensive
        return None

__all__ = [
    'IST','UTC','MARKET_OPEN','MARKET_CLOSE','PRE_MARKET_START','POST_MARKET_END',
    'get_ist_now','get_utc_now','utc_now','isoformat_z','ensure_utc_helpers','ist_to_utc','utc_to_ist',
    'is_market_open','market_hours_check','next_market_open','time_until_market_open','format_ist_time',
    'get_market_session_bounds','compute_weekly_expiry','compute_next_weekly_expiry','compute_monthly_expiry',
    'compute_next_monthly_expiry','round_timestamp','format_rounded_timestamp','round_to_30s_ist','format_ist_hms_30s',
    'format_any_to_ist_hms_30s','format_ist_dt_30s','format_any_to_ist_dt_30s'
]
