"""Rate limiter & throttled logging helpers (A7 Step 6 extraction).

Encapsulates provider-specific construction & throttled log guards that were
inline in `kite_provider.py`. Keeping them separate reduces facade clutter and
enables reuse should additional providers adopt identical throttling semantics.
"""
from __future__ import annotations

import time
from typing import Protocol, TypedDict

from src.utils.rate_limiter import RateLimiter


class _SettingsLike(Protocol):
    """Minimal protocol for settings objects consumed here.

    Only the ``kite_throttle_ms`` attribute is accessed and it can be any
    truthy/falsy value that ``int()`` can coerce (including None/str/number).
    """

    kite_throttle_ms: object | None


class ThrottleFlags(TypedDict):
    """Typed dict holding throttled logging timestamps."""

    last_log_ts: float
    last_quote_log_ts: float

def setup_api_rate_limiter(settings: _SettingsLike) -> RateLimiter | None:
    ms = int(getattr(settings, 'kite_throttle_ms', 0) or 0)
    return RateLimiter(ms / 1000.0) if ms > 0 else None


def make_throttled_flags() -> ThrottleFlags:
    return {
        'last_log_ts': 0.0,
        'last_quote_log_ts': 0.0,
    }


def log_allowed(flags: ThrottleFlags, interval: float = 5.0) -> bool:
    now = time.time()
    if now - flags['last_log_ts'] > interval:
        flags['last_log_ts'] = now
        return True
    return False


def quote_log_allowed(flags: ThrottleFlags, interval: float = 5.0) -> bool:
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
