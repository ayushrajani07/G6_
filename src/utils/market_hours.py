"""
Market Hours Utility for G6 Platform
Handles trading hours detection and scheduling.
"""

from __future__ import annotations

import logging
import os

# Add this before launching the subprocess
import sys  # noqa: F401
import time
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

DEFAULT_MARKET_HOURS = {
    "equity": {
        # Premarket window strictly for system setup; collection remains gated until 09:15 IST.
        "premarket": {"start": "08:30:00", "end": "09:15:00"},
        "pre_open": {"start": "09:00:00", "end": "09:15:00"},
        "regular": {"start": "09:15:00", "end": "15:30:00"},
        "post_close": {"start": "15:30:00", "end": "15:45:00"},
    },
    "currency": {
        "regular": {"start": "09:00:00", "end": "17:00:00"},
    },
    "commodity": {
        "regular": {"start": "09:00:00", "end": "23:30:00"},
    }
}

MARKET_HOLIDAYS_2025 = [
    # Republic Day
    "2025-01-26",
    # Mahashivratri
    "2025-02-26",
    # Holi
    "2025-03-17",
    # Good Friday
    "2025-04-18",
    # Maharashtra Day
    "2025-05-01",
    # Independence Day
    "2025-08-15",
    # Gandhi Jayanti
    "2025-10-02",
    # Diwali
    "2025-11-12",
    # Christmas
    "2025-12-25"
]

def _weekend_mode() -> bool:
    # Weekend mode removed; always False (weekends treated as closed unless explicit holiday override logic changes)
    return False

def is_market_open(
    *,
    market_type: str = "equity",
    session_type: str = "regular",
    reference_time: datetime | None = None,
    holidays: list | None = None
) -> bool:
    """
    Check if the market is currently open.
    
    Args:
        market_type: Type of market (equity, currency, commodity)
        session_type: Type of session (pre_open, regular, post_close)
        reference_time: Time to check (default is current time)
        holidays: List of holiday dates as strings (YYYY-MM-DD)
        
    Returns:
        bool: True if market is open, False otherwise
    """
    now = reference_time or datetime.now(UTC)

    # Convert to IST (+5:30)
    ist_offset = timedelta(hours=5, minutes=30)
    ist_now = now + ist_offset

    # Check weekday (0=Monday, 6=Sunday) unless weekend override enabled
    if ist_now.weekday() >= 5:  # Saturday or Sunday
        return False

    # Check holidays
    holiday_list = holidays or MARKET_HOLIDAYS_2025
    if ist_now.strftime("%Y-%m-%d") in holiday_list:
        return False

    # Get market hours
    hours = DEFAULT_MARKET_HOURS.get(market_type, {}).get(session_type)
    if not hours:
        return False

    # Parse times
    start_time = datetime.strptime(hours["start"], "%H:%M:%S").time()
    end_time = datetime.strptime(hours["end"], "%H:%M:%S").time()
    current_time = ist_now.time()

    return start_time <= current_time < end_time

def get_next_market_open(
    *,
    market_type: str = "equity",
    session_type: str = "regular",
    reference_time: datetime | None = None,
    holidays: list | None = None
) -> datetime:
    """
    Get the next market open time.
    
    Args:
        market_type: Type of market (equity, currency, commodity)
        session_type: Type of session (pre_open, regular, post_close)
        reference_time: Time to check from (default is current time)
        holidays: List of holiday dates as strings (YYYY-MM-DD)
        
    Returns:
        datetime: Next market open time in UTC
    """
    now = reference_time or datetime.now(UTC)

    # Convert to IST (+5:30)
    ist_offset = timedelta(hours=5, minutes=30)
    ist_now = now + ist_offset

    # Get market hours
    hours = DEFAULT_MARKET_HOURS.get(market_type, {}).get(session_type)
    if not hours:
        raise ValueError(f"Invalid market_type ({market_type}) or session_type ({session_type})")

    # Parse start time
    start_time = datetime.strptime(hours["start"], "%H:%M:%S").time()

    # Create target datetime for today
    target_date = ist_now.date()
    target_datetime = datetime.combine(target_date, start_time)

    # If target time is already passed, move to next day
    if ist_now.time() >= start_time:
        target_date = target_date + timedelta(days=1)
        target_datetime = datetime.combine(target_date, start_time)

    # Skip weekends and holidays
    holiday_list = holidays or MARKET_HOLIDAYS_2025
    while target_date.weekday() >= 5 or target_date.strftime("%Y-%m-%d") in holiday_list:
        target_date = target_date + timedelta(days=1)
        target_datetime = datetime.combine(target_date, start_time)

    # Convert back to UTC
    utc_datetime = target_datetime - ist_offset
    return utc_datetime.replace(tzinfo=UTC)

def sleep_until_market_open(
    *,
    market_type: str = "equity",
    session_type: str = "regular",
    check_interval: int = 60,
    on_wait_start=None,
    on_wait_tick=None
) -> None:
    """
    Sleep until market opens.
    
    Args:
        market_type: Type of market (equity, currency, commodity)
        session_type: Type of session (pre_open, regular, post_close)
        check_interval: Interval to check market status in seconds
        on_wait_start: Callback when wait starts, receives next_open as parameter
        on_wait_tick: Callback on each check, receives seconds_remaining as parameter
    """
    if is_market_open(market_type=market_type, session_type=session_type):
        return

    next_open = get_next_market_open(market_type=market_type, session_type=session_type)

    if on_wait_start:
        on_wait_start(next_open)

    while True:
        now = datetime.now(UTC)
        if is_market_open(market_type=market_type, session_type=session_type, reference_time=now):
            break

        seconds_remaining = int((next_open - now).total_seconds())
        if seconds_remaining <= 0:
            break

        if on_wait_tick:
            on_wait_tick(seconds_remaining)

        # Sleep for check interval or remaining time, whichever is smaller
        sleep_time = min(check_interval, seconds_remaining)
        time.sleep(sleep_time)


def is_premarket_window(reference_time: datetime | None = None) -> bool:
    """Return True if current time is within the premarket initialization window (IST 08:30–09:15) and
    the regular session has not yet started.

    This allows the platform to perform provider authentication, warm caches, and run integrity /
    readiness checks without starting full data collection cycles prematurely.
    """
    # Within premarket session AND not yet regular session.
    return (
        is_market_open(market_type="equity", session_type="premarket", reference_time=reference_time)
        and not is_market_open(market_type="equity", session_type="regular", reference_time=reference_time)
    )


__all__ = [
    # Existing exports implicitly relied upon by other modules
    'is_market_open', 'get_next_market_open', 'sleep_until_market_open',
    # New helper
    'is_premarket_window'
]

# ---------------------------------------------------------------------------
# Holiday utilities for expiry adjustment (Phase 10 enhancement)
# ---------------------------------------------------------------------------
def _parse_env_holidays() -> list[str]:
    """Parse additional holidays from G6_HOLIDAYS env (comma or space separated)."""
    raw = os.environ.get('G6_HOLIDAYS','').strip()
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(';',',').replace('\n',',').split(',') if p.strip()]
    # Accept also space separated tokens if no commas present
    if len(parts) == 1 and ' ' in parts[0]:
        parts = [p.strip() for p in parts[0].split(' ') if p.strip()]
    # Basic YYYY-MM-DD validation
    out = []
    for p in parts:
        if len(p)==10 and p[4]=='-' and p[7]=='-':
            out.append(p)
    return out

def get_holiday_list(base: list[str] | None = None) -> list[str]:
    """Return merged holiday list (static + env overrides)."""
    base_list = list(base) if base else list(MARKET_HOLIDAYS_2025)
    env_extra = _parse_env_holidays()
    merged = list(dict.fromkeys(base_list + env_extra))  # de-duplicate preserve order
    return merged

def adjust_expiry_for_holiday(expiry_date, *, roll_strategy: str = 'previous', holidays: list[str] | None = None):
    """Adjust an expiry date if it falls on a holiday.

    Args:
        expiry_date (date): Candidate expiry.
        roll_strategy: 'previous' (default) or 'next'.
        holidays: Optional explicit holiday list.

    Returns:
        date: Adjusted date (or original if no change needed).
    """
    from datetime import timedelta
    if not expiry_date:
        return expiry_date
    hols = holidays or get_holiday_list()
    try:
        exp_str = expiry_date.strftime('%Y-%m-%d')
    except Exception:
        return expiry_date
    if exp_str not in hols:
        return expiry_date
    # Apply strategy
    delta = -1 if roll_strategy == 'previous' else 1
    cur = expiry_date
    # Skip weekends & holidays
    while True:
        cur = cur + timedelta(days=delta)
        if cur.weekday() >=5:
            continue
        if cur.strftime('%Y-%m-%d') in hols:
            continue
        return cur
