#!/usr/bin/env python3
"""
Lightweight circuit breaker for Influx write path.

States:
- CLOSED: all requests allowed; failures increment counter; when threshold reached -> OPEN
- OPEN: requests short-circuited until reset timeout elapses -> HALF_OPEN
- HALF_OPEN: allow a single trial; success -> CLOSED (reset counters), failure -> OPEN

This module intentionally avoids external deps; thread-safe via a simple lock.
"""
from __future__ import annotations

import threading
import time


class InfluxCircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: float = 30.0):
        self.failure_threshold = max(1, int(failure_threshold))
        self.reset_timeout = float(reset_timeout)
        self._lock = threading.Lock()
        self._state = "CLOSED"  # CLOSED | OPEN | HALF_OPEN
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._half_open_in_flight = False

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    def allow(self) -> bool:
        """Return True if a write attempt is allowed under current state."""
        with self._lock:
            now = time.time()
            if self._state == "OPEN":
                if self._opened_at is not None and (now - self._opened_at) >= self.reset_timeout:
                    # Move to HALF_OPEN to probe
                    self._state = "HALF_OPEN"
                    self._half_open_in_flight = False
                else:
                    return False
            if self._state == "HALF_OPEN":
                if not self._half_open_in_flight:
                    self._half_open_in_flight = True
                    return True
                return False
            # CLOSED
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._state in ("HALF_OPEN", "OPEN"):
                self._state = "CLOSED"
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_in_flight = False

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive_failures += 1
            if self._state == "HALF_OPEN":
                # Trip immediately on failure
                self._state = "OPEN"
                self._opened_at = time.time()
                self._half_open_in_flight = False
                return
            if self._consecutive_failures >= self.failure_threshold:
                self._state = "OPEN"
                self._opened_at = time.time()


__all__ = ["InfluxCircuitBreaker"]
