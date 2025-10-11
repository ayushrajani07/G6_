#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A tiny connection pool for InfluxDBClient to avoid reconnect churn and share clients.
Uses a simple LIFO stack for clients. Thread-safe with a lock and condition.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional, List


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
        self._items: List[object] = []
        self._total_created = 0
        self._cond = threading.Condition(self._lock)
        # Pre-warm
        for _ in range(self._min):
            self._items.append(self._factory())
            self._total_created += 1

    def acquire(self, timeout: Optional[float] = None) -> object:
        with self._cond:
            if self._items:
                return self._items.pop()
            if self._total_created < self._max:
                self._total_created += 1
                return self._factory()
            # Wait for a release
            if not self._cond.wait(timeout or 5.0):
                # timed out; try again if available
                if self._items:
                    return self._items.pop()
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
