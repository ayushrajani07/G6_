"""Lightweight trading calendar utilities for overlays.

Features:
- Determine if a given date is a trading day (Mon-Fri excluding configured holidays)
- Holidays file path can be provided via env var G6_CALENDAR_HOLIDAYS_JSON
  or defaults to '<workspace>/data/weekday_master/_calendar/holidays.json' if present.

The module caches loaded holidays for efficiency.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

_HOLIDAYS_CACHE: set[date] | None = None
_HOLIDAYS_PATH_CACHE: str | None = None


def _default_holidays_path() -> Path:
    # Default to repository-relative location commonly used by overlays
    return Path('data') / 'weekday_master' / '_calendar' / 'holidays.json'


def _load_holidays_from(path: Path) -> set[date]:
    holidays: set[date] = set()
    if not path.exists():
        return holidays
    try:
        with path.open('r', encoding='utf-8') as f:
            data = json.load(f)
        # Accept list of strings YYYY-MM-DD or nested under key 'holidays'
        if isinstance(data, dict) and 'holidays' in data:
            items = data.get('holidays', [])
        else:
            items = data
        for s in items or []:
            try:
                parts = [int(x) for x in str(s).split('-')]
                if len(parts) == 3:
                    holidays.add(date(parts[0], parts[1], parts[2]))
            except Exception:
                # Skip bad entries silently
                continue
    except Exception:
        # On any parse error, treat as no holidays rather than failing pipeline
        return set()
    return holidays


def get_holidays() -> set[date]:
    """Return a cached set of holiday dates.

    Resolution order for the holidays file:
    1) G6_CALENDAR_HOLIDAYS_JSON (env var absolute or relative path)
    2) data/weekday_master/_calendar/holidays.json (if exists)
    Otherwise returns an empty set.
    """
    global _HOLIDAYS_CACHE, _HOLIDAYS_PATH_CACHE
    env_path = os.environ.get('G6_CALENDAR_HOLIDAYS_JSON')
    path_str = env_path or str(_default_holidays_path())
    if _HOLIDAYS_CACHE is not None and _HOLIDAYS_PATH_CACHE == path_str:
        return _HOLIDAYS_CACHE
    path = Path(path_str)
    _HOLIDAYS_CACHE = _load_holidays_from(path)
    _HOLIDAYS_PATH_CACHE = path_str
    return _HOLIDAYS_CACHE


def is_trading_day(d: date) -> bool:
    """Return True if the given date is a trading day: Monday-Friday and not a holiday.

    Weekends (Saturday=5, Sunday=6) are non-trading.
    Holidays are loaded via get_holidays().
    """
    if d.weekday() >= 5:  # 5=Saturday, 6=Sunday
        return False
    return d not in get_holidays()
