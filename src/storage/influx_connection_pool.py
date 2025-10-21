#!/usr/bin/env python3
"""
A tiny connection pool for InfluxDBClient to avoid reconnect churn and share clients.
Uses a simple LIFO stack for clients. Thread-safe with a lock and condition.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable


class InfluxConnectionPool:
    def __init__(
        self,
        factory: Callable[[], object],
        min_size: int = 1,
        max_size: int = 4,
    ) -> None:
        self._factory = factory
        self._min = max(0, int(min_size))
        self._max = max(self._min or 1, int(max_size))
        self._lock = threading.Lock()
        self._items: list[object] = []
        self._total_created = 0
        self._cond = threading.Condition(self._lock)
        # Pre-warm
        for _ in range(self._min):
            self._items.append(self._factory())
            self._total_created += 1

    def acquire(self, timeout: float | None = None) -> object:
        """Acquire a client from the pool.

        If an item is available, return immediately. If capacity remains, create
        a new client via the factory. Otherwise, wait until an item is released
        or the optional timeout elapses.
        """
        deadline: float | None = None
        if timeout is not None:
            # Use monotonic clock to avoid issues with system time adjustments
            deadline = time.monotonic() + max(0.0, float(timeout))
        with self._cond:
            while True:
                if self._items:
                    return self._items.pop()
                if self._total_created < self._max:
                    self._total_created += 1
                    return self._factory()
                # Compute remaining time (None => indefinite wait with periodic wake)
                remaining: float | None
                if deadline is None:
                    remaining = 5.0  # periodic wake to re-check conditions
                else:
                    remaining = max(0.0, deadline - time.monotonic())
                    if remaining == 0.0:
                        raise TimeoutError("InfluxConnectionPool acquire timeout")
                signaled = self._cond.wait(remaining)
                # On spurious wakeups or time-slice expiry, loop and re-check
                if deadline is not None and not signaled:
                    # Timed out waiting in this iteration
                    raise TimeoutError("InfluxConnectionPool acquire timeout")

    def release(self, client: object) -> None:
        with self._cond:
            self._items.append(client)
            self._cond.notify()

    def size(self) -> int:
        with self._lock:
            return len(self._items)

    def total_created(self) -> int:
        with self._lock:
            return self._total_created

    def close_all(self) -> None:
        with self._lock:
            while self._items:
                c = self._items.pop()
                try:
                    close_fn = getattr(c, "close", None)
                    if callable(close_fn):
                        close_fn()
                except Exception:
                    pass


__all__ = ["InfluxConnectionPool"]
