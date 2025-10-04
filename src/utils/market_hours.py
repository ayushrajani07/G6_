# -*- coding: utf-8 -*-
"""
Market Hours Utility for G6 Platform
Handles trading hours detection and scheduling.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
import os
from typing import Dict, Optional, Tuple, Union

# Add this before launching the subprocess
import sys  # noqa: F401
import os  # noqa: F401

logger = logging.getLogger(__name__)

DEFAULT_MARKET_HOURS = {
    "equity": {
        # New broader premarket initialization window (platform bootstrap, auth, health checks)
        # Collection cycles remain gated until regular session opens at 09:15 IST.
        "premarket": {"start": "08:00:00", "end": "09:15:00"},
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
    return os.getenv('G6_WEEKEND_MODE', '0').lower() in ('1','true','on','yes')

def is_market_open(
    *, 
    market_type: str = "equity",
    session_type: str = "regular",
    reference_time: Optional[datetime] = None,
    holidays: Optional[list] = None
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
    now = reference_time or datetime.now(timezone.utc)
    
    # Convert to IST (+5:30)
    ist_offset = timedelta(hours=5, minutes=30)
    ist_now = now + ist_offset
    
    # Check weekday (0=Monday, 6=Sunday) unless weekend override enabled
    if ist_now.weekday() >= 5 and not _weekend_mode():  # Saturday or Sunday
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
    reference_time: Optional[datetime] = None,
    holidays: Optional[list] = None
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
    now = reference_time or datetime.now(timezone.utc)
    
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
    if not _weekend_mode():
        while target_date.weekday() >= 5 or target_date.strftime("%Y-%m-%d") in holiday_list:
            target_date = target_date + timedelta(days=1)
            target_datetime = datetime.combine(target_date, start_time)
    else:
        # Still skip holidays even if weekend mode is active
        while target_date.strftime("%Y-%m-%d") in holiday_list:
            target_date = target_date + timedelta(days=1)
            target_datetime = datetime.combine(target_date, start_time)
    
    # Convert back to UTC
    utc_datetime = target_datetime - ist_offset
    return utc_datetime.replace(tzinfo=timezone.utc)

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
        now = datetime.now(timezone.utc)
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


def is_premarket_window(reference_time: Optional[datetime] = None) -> bool:
    """Return True if current time is within the premarket initialization window (IST 08:00–09:15) and
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