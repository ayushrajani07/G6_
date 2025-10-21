"""Token-bucket rate limiter for provider calls.

Features:
- Token bucket with configurable rate (tokens/sec) and burst capacity
- Thread-safe try_acquire for fast paths
- Async acquire helper for asyncio flows (cooperative sleeping)
- Optional time function injection for deterministic tests
- Noop limiter when rate <= 0 or burst <= 0 (unlimited)
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable


class _NoopLimiter:
    """Unlimited limiter: always allows immediately."""

    __slots__ = ()

    def try_acquire(self, n: int = 1) -> bool:  # noqa: D401
        return True

    async def acquire(self, n: int = 1) -> None:
        return None


class TokenBucket:
    """Simple, efficient token-bucket limiter.

    Args:
        rate: tokens per second (float). Use logical units (calls/sec).
        burst: max bucket capacity in tokens (int > 0).
        time_func: function returning monotonic seconds; defaults to time.monotonic.
    """

    __slots__ = ("_rate", "_burst", "_tokens", "_last", "_lock", "_time")

    def __init__(
        self,
        rate: float,
        burst: int,
        *,
        time_func: Callable[[], float] | None = None,
    ) -> None:
        if rate <= 0 or burst <= 0:
            # Delegate to _NoopLimiter semantics by raising; factory creates noop.
            raise ValueError("TokenBucket requires rate > 0 and burst > 0")
        self._rate = float(rate)
        self._burst = int(burst)
        self._tokens: float = float(burst)
        self._last: float = (time_func or time.monotonic)()
        self._lock = threading.Lock()
        self._time = time_func or time.monotonic

    def _refill(self, now: float) -> None:
        # Refill tokens based on elapsed time since last check
        elapsed = max(0.0, now - self._last)
        if elapsed <= 0:
            return
        self._last = now
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)

    def try_acquire(self, n: int = 1) -> bool:
        """Fast non-blocking attempt to acquire n tokens.

        Returns True if granted; False otherwise.
        Thread-safe and low overhead.
        """
        if n <= 0:
            return True
        now = self._time()
        with self._lock:
            self._refill(now)
            if self._tokens >= n:
                self._tokens -= n
                return True
            return False

    async def acquire(self, n: int = 1) -> None:
        """Await until n tokens can be acquired.

        Uses small cooperative sleeps. Suitable for asyncio paths.
        """
        if n <= 0:
            return
        # Backoff parameters: compute precise sleep for deficit, clamp to [0.001, 0.1]
        min_sleep = 0.001
        max_sleep = 0.1
        while True:
            if self.try_acquire(n):
                return
            # Estimate time needed for at least one token
            now = self._time()
            with self._lock:
                # Recompute deficit more precisely under lock
                self._refill(now)
                deficit = max(0.0, n - self._tokens)
            if deficit <= 0:
                # Loop will succeed next iteration immediately
                await asyncio.sleep(0)
                continue
            sleep_for = min(max(deficit / self._rate, min_sleep), max_sleep)
            await asyncio.sleep(sleep_for)


class RateLimiterRegistry:
    """Registry to reuse per-provider limiters.

    Use get(name, rate, burst) to obtain a limiter. If rate<=0 or burst<=0, returns a noop limiter.
    Thread-safe for concurrent get calls.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, TokenBucket | _NoopLimiter] = {}

    def get(self, name: str, rate: float, burst: int) -> TokenBucket | _NoopLimiter:
        if rate <= 0 or burst <= 0:
            return _NoopLimiter()
        key = f"{name}:{rate}:{burst}"
        with self._lock:
            limiter = self._by_name.get(key)
            if limiter is None:
                limiter = TokenBucket(rate, burst)
                self._by_name[key] = limiter
            return limiter


__all__ = ["TokenBucket", "RateLimiterRegistry"]
