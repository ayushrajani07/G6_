"""Rate limiter & throttled logging helpers (A7 Step 6 extraction).

Encapsulates provider-specific construction & throttled log guards that were
inline in `kite_provider.py`. Keeping them separate reduces facade clutter and
enables reuse should additional providers adopt identical throttling semantics.
"""
from __future__ import annotations

import time
from typing import Optional

from src.utils.rate_limiter import RateLimiter

def setup_api_rate_limiter(settings) -> Optional[RateLimiter]:
    ms = int(getattr(settings, 'kite_throttle_ms', 0) or 0)
    return RateLimiter(ms / 1000.0) if ms > 0 else None


def make_throttled_flags():
    return {
        'last_log_ts': 0.0,
        'last_quote_log_ts': 0.0,
    }


def log_allowed(flags: dict, interval: float = 5.0) -> bool:
    now = time.time()
    if now - flags['last_log_ts'] > interval:
        flags['last_log_ts'] = now
        return True
    return False


def quote_log_allowed(flags: dict, interval: float = 5.0) -> bool:
    now = time.time()
    if now - flags['last_quote_log_ts'] > interval:
        flags['last_quote_log_ts'] = now
        return True
    return False

__all__ = [
    'setup_api_rate_limiter',
    'make_throttled_flags',
    'log_allowed',
    'quote_log_allowed',
]
