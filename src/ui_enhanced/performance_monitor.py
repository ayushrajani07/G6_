"""Lightweight performance sampler placeholder.
Samples process CPU and memory every N seconds in a background thread.
Falls back gracefully if psutil not available.
"""
from __future__ import annotations

import threading
from typing import Any

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

class PerformanceMonitor:
    def __init__(self, interval: int = 5):
        self.interval = interval
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.latest: dict[str, Any] = {}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="PerfMon", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            try:
                if psutil:
                    p = psutil.Process()
                    with p.oneshot():
                        cpu = p.cpu_percent(interval=None)  # returns last interval; may be 0 first call
                        mem = p.memory_info().rss / (1024*1024)
                    self.latest = {"cpu_pct": cpu, "memory_mb": mem}
                else:
                    self.latest = {}
            except Exception:
                pass
            self._stop.wait(self.interval)

__all__ = ["PerformanceMonitor"]
