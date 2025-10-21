#!/usr/bin/env python3
"""
InfluxBufferManager: batches points and flushes periodically or when batch_size is hit.
Includes retry with exponential backoff and integrates with a circuit breaker via callback.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any


class InfluxBufferManager:
    def __init__(
        self,
        write_fn: Callable[[list[Any]], None],
        batch_size: int = 500,
        flush_interval: float = 1.0,
        max_queue_size: int = 10_000,
        max_retries: int = 3,
        backoff_base: float = 0.25,
        on_success: Callable[[int], None] | None = None,
        on_failure: Callable[[Exception], None] | None = None,
    ) -> None:
        self._write_fn = write_fn
        self._batch_size = max(1, int(batch_size))
        self._flush_interval = float(flush_interval)
        self._max_queue = max(100, int(max_queue_size))
        self._max_retries = max(0, int(max_retries))
        self._backoff_base = float(backoff_base)
        self._buf: list[Any] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._last_flush = time.time()
        self._thread = threading.Thread(target=self._loop, name="influx-buffer", daemon=True)
        self._on_success = on_success
        self._on_failure = on_failure
        self._thread.start()

    def add(self, point: Any) -> None:
        with self._lock:
            if len(self._buf) >= self._max_queue:
                # drop oldest to avoid unbounded growth
                self._buf.pop(0)
            self._buf.append(point)
            if len(self._buf) >= self._batch_size:
                self._flush_locked()

    def add_many(self, points: list[Any]) -> None:
        with self._lock:
            if len(points) >= self._max_queue:
                points = points[-self._max_queue :]
            # if buffer + points exceeds max, keep tail
            new_size = len(self._buf) + len(points)
            if new_size > self._max_queue:
                drop = new_size - self._max_queue
                if drop > 0:
                    self._buf = self._buf[drop:]
            self._buf.extend(points)
            if len(self._buf) >= self._batch_size:
                self._flush_locked()

    def _loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(self._flush_interval)
            with self._lock:
                if (time.time() - self._last_flush) >= self._flush_interval and self._buf:
                    self._flush_locked()

    def _flush_locked(self) -> None:
        to_send = self._buf
        self._buf = []
        self._last_flush = time.time()
        # send outside lock
        self._send(to_send)

    def _send(self, points: list[Any]) -> None:
        # retry with backoff
        for attempt in range(self._max_retries + 1):
            try:
                if points:
                    self._write_fn(points)
                if self._on_success:
                    self._on_success(len(points))
                return
            except Exception as e:  # noqa: BLE001
                if self._on_failure:
                    self._on_failure(e)
                if attempt >= self._max_retries:
                    return
                time.sleep(self._backoff_base * (2**attempt))

    def flush(self) -> None:
        with self._lock:
            if self._buf:
                self._flush_locked()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass
        self.flush()


__all__ = ["InfluxBufferManager"]
