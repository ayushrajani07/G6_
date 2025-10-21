"""Lightweight token-bucket rate limiter & cooldown for Kite API calls.

Phase 1: Minimal implementation (no external deps, thread-safe, low overhead).

Environment variables (all optional):
  G6_KITE_QPS                       : Sustained allowed requests per second (default 3)
  G6_KITE_RATE_MAX_BURST            : Bucket capacity (default = 2 * QPS)
  G6_KITE_RATE_CONSECUTIVE_THRESHOLD: Consecutive rate-limit errors to open cooldown (default 5)
  G6_KITE_RATE_COOLDOWN_SECONDS     : Cooldown length in seconds (default 20)

The caller is expected to:
  * invoke acquire() before issuing a network call
  * call record_rate_limit_error() when a 429 / "Too many requests" is observed
  * call record_success() on any successful call (resets consecutive counter)

Cooldown semantics: while in cooldown, acquire() will sleep the remaining cooldown
time (once) or, if fast_fail=True, raise RateLimitedError immediately.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass


class RateLimitedError(RuntimeError):
    """Raised to signal the caller that the request should be delayed / skipped."""


@dataclass
class _State:
    capacity: int
    tokens: float
    refill_rate: float  # tokens per second
    last_refill: float
    consecutive_rl: int = 0
    cooldown_until: float = 0.0


class RateLimiter:
    def __init__(self,
                 qps: int = 3,
                 burst: int | None = None,
                 consecutive_threshold: int = 5,
                 cooldown_seconds: int = 20):
        qps = max(1, qps)
        cap = burst if (burst and burst > 0) else qps * 2
        now = time.time()
        self._st = _State(capacity=cap, tokens=float(cap), refill_rate=float(qps), last_refill=now)
        self._lock = threading.Lock()
        self._consecutive_threshold = max(1, consecutive_threshold)
        self._cooldown_seconds = max(1, cooldown_seconds)

    def _refill(self, now: float) -> None:
        st = self._st
        if now <= st.last_refill:
            return
        delta = now - st.last_refill
        add = delta * st.refill_rate
        if add > 0:
            st.tokens = min(st.capacity, st.tokens + add)
            st.last_refill = now

    def acquire(self, tokens: float = 1.0, *, fast_fail: bool = False) -> None:
        """Acquire tokens (default 1). Blocks minimally until available.

        If in cooldown: either raise RateLimitedError (fast_fail) or sleep until end.
        """
        while True:
            now = time.time()
            with self._lock:
                st = self._st
                # Cooldown check
                if st.cooldown_until and now < st.cooldown_until:
                    if fast_fail:
                        raise RateLimitedError("rate_limited_cooldown")
                    sleep_for = st.cooldown_until - now
                else:
                    sleep_for = 0.0
                if sleep_for > 0:
                    pass  # release lock & sleep below
                else:
                    self._refill(now)
                    if st.tokens >= tokens:
                        st.tokens -= tokens
                        return
                    # compute minimal wait for next token
                    needed = tokens - st.tokens
                    # time = needed / refill_rate
                    sleep_for = needed / st.refill_rate if st.refill_rate > 0 else 0.5
            if sleep_for > 0:
                time.sleep(min(sleep_for, 1.0))  # cap small sleeps to 1s to stay responsive

    def record_rate_limit_error(self) -> None:
        with self._lock:
            self._st.consecutive_rl += 1
            if self._st.consecutive_rl >= self._consecutive_threshold:
                self._st.cooldown_until = time.time() + self._cooldown_seconds

    def record_success(self) -> None:
        with self._lock:
            self._st.consecutive_rl = 0
            # Do not clear cooldown prematurely; success outside cooldown naturally proceeds
            if self._st.cooldown_until and time.time() >= self._st.cooldown_until:
                self._st.cooldown_until = 0.0

    def cooldown_active(self) -> bool:
        with self._lock:
            return bool(self._st.cooldown_until and time.time() < self._st.cooldown_until)


def build_default_rate_limiter() -> RateLimiter:
    qps = int(os.getenv('G6_KITE_QPS', '3') or 3)
    burst_env = os.getenv('G6_KITE_RATE_MAX_BURST')
    burst = int(burst_env) if burst_env and burst_env.isdigit() else None
    thr = int(os.getenv('G6_KITE_RATE_CONSECUTIVE_THRESHOLD', '5') or 5)
    cd = int(os.getenv('G6_KITE_RATE_COOLDOWN_SECONDS', '20') or 20)
    return RateLimiter(qps=qps, burst=burst, consecutive_threshold=thr, cooldown_seconds=cd)

__all__ = ["RateLimiter", "RateLimitedError", "build_default_rate_limiter"]
