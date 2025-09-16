# -*- coding: utf-8 -*-
"""
Time Utilities for G6 Platform
Consolidated time utilities from various modules.
"""

from __future__ import annotations

import pytz
from datetime import datetime, date, time as dt_time, timedelta
from typing import Optional, Tuple, Union

# Timezones
IST = pytz.timezone('Asia/Kolkata')
UTC = pytz.UTC

# Market hours (IST)
MARKET_OPEN = dt_time(9, 15)  # 9:15 AM
MARKET_CLOSE = dt_time(15, 30)  # 3:30 PM

# Pre-market and post-market
PRE_MARKET_START = dt_time(9, 0)   # 9:00 AM
POST_MARKET_END = dt_time(16, 0)   # 4:00 PM

def get_ist_now() -> datetime:
    """Get current time in IST."""
    return datetime.now(IST)

def get_utc_now() -> datetime:
    """Get current time in UTC.""" 
    return datetime.now(UTC)

def ist_to_utc(ist_dt: datetime) -> datetime:
    """Convert IST datetime to UTC."""
    if ist_dt.tzinfo is None:
        ist_dt = IST.localize(ist_dt)
    return ist_dt.astimezone(UTC)

def utc_to_ist(utc_dt: datetime) -> datetime:
    """Convert UTC datetime to IST."""
    if utc_dt.tzinfo is None:
        utc_dt = UTC.localize(utc_dt)
    return utc_dt.astimezone(IST)

def is_market_open(check_time: Optional[datetime] = None) -> bool:
    """Check if market is currently open."""
    if check_time is None:
        check_time = get_ist_now()
    elif check_time.tzinfo != IST:
        check_time = check_time.astimezone(IST)
    
    # Check if weekday (Monday=0, Sunday=6)
    if check_time.weekday() >= 5:  # Saturday or Sunday
        return False
        
    current_time = check_time.time()
    return MARKET_OPEN <= current_time <= MARKET_CLOSE

def market_hours_check(check_time: Optional[datetime] = None) -> Tuple[bool, str]:
    """Detailed market hours check with status message."""
    if check_time is None:
        check_time = get_ist_now()
    elif check_time.tzinfo != IST:
        check_time = check_time.astimezone(IST)
    
    weekday = check_time.weekday()
    current_time = check_time.time()
    
    if weekday >= 5:  # Weekend
        return False, "market_closed_weekend"
        
    if current_time < PRE_MARKET_START:
        return False, "before_premarket"
    elif current_time < MARKET_OPEN:
        return False, "premarket"
    elif current_time <= MARKET_CLOSE:
        return True, "market_open"
    elif current_time <= POST_MARKET_END:
        return False, "post_market"
    else:
        return False, "market_closed"

def next_market_open(from_time: Optional[datetime] = None) -> datetime:
    """Get next market opening time."""
    if from_time is None:
        from_time = get_ist_now()
    elif from_time.tzinfo != IST:
        from_time = from_time.astimezone(IST)
    
    # Start from next day if market is closed today
    check_date = from_time.date()
    if from_time.time() > MARKET_CLOSE or from_time.weekday() >= 5:
        check_date = from_time.date() + timedelta(days=1)
        
    # Find next weekday
    while check_date.weekday() >= 5:  # Skip weekends
        check_date = check_date + timedelta(days=1)
    
    return IST.localize(datetime.combine(check_date, MARKET_OPEN))

def time_until_market_open(from_time: Optional[datetime] = None) -> float:
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

def get_market_session_bounds(trade_date: Optional[date] = None) -> Tuple[datetime, datetime]:
    """Get market session start and end times for a date."""
    if trade_date is None:
        trade_date = get_ist_now().date()
        
    start = IST.localize(datetime.combine(trade_date, MARKET_OPEN))
    end = IST.localize(datetime.combine(trade_date, MARKET_CLOSE))
    
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

def compute_weekly_expiry(now_date: Union[datetime, date], weekly_dow: int = 3) -> date:
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

def compute_next_weekly_expiry(now_date: Union[datetime, date], weekly_dow: int = 3) -> date:
    """Compute next weekly expiry after the current one."""
    this_week = compute_weekly_expiry(now_date, weekly_dow)
    return _next_weekday_on_or_after(this_week + timedelta(days=1), weekly_dow)

def compute_monthly_expiry(now_date: Union[datetime, date], monthly_dow: int = 3) -> date:
    """Compute monthly expiry (last Thursday of month by default)."""
    # Convert to date if datetime
    if isinstance(now_date, datetime):
        check_date = now_date.date()
    else:
        check_date = now_date
        
    return _last_weekday_of_month(check_date, monthly_dow)

def compute_next_monthly_expiry(now_date: Union[datetime, date], monthly_dow: int = 3) -> date:
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