"""Lightweight rate limiting helper for logging hot paths.

Usage:
    from src.utils.rate_limiter import RateLimiter
    rl = RateLimiter(min_interval=30)  # seconds
    if rl():
        logger.warning("This warning will appear at most every 30s")

Thread-safe (uses a lock) and low overhead. Stores last emit timestamp.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class RateLimiter:
    __slots__ = ("_min_interval", "_last", "_lock")

    def __init__(self, min_interval: float = 60.0) -> None:
        self._min_interval = float(min_interval)
        self._last: float = 0.0
        self._lock = threading.Lock()

    def ready(self) -> bool:
        now = time.time()
        with self._lock:
            if now - self._last >= self._min_interval:
                self._last = now
                return True
        return False

    # Allow instance to be called directly
    __call__ = ready

def rate_limited(min_interval: float) -> Callable[[], bool]:
    """Decorator returning a predicate wrapper you can call to decide logging.

    Example:
        should_log = rate_limited(10)
        if should_log():
            logger.info("Printed at most every 10s")
    """
    rl = RateLimiter(min_interval=min_interval)
    return rl.ready
