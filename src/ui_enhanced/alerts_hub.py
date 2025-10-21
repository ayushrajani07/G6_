"""Central alerts hub placeholder.
Collects important runtime alerts for surfacing in enhanced live panel.
"""
from __future__ import annotations

from collections import deque
from threading import Lock


class AlertsHub:
    def __init__(self, max_items: int = 100):
        self.max_items = max_items
        self._items: deque[str] = deque(maxlen=max_items)
        self._lock = Lock()

    def push(self, msg: str):
        with self._lock:
            self._items.appendleft(msg)

    def snapshot(self, limit: int = 5) -> list[str]:
        with self._lock:
            return list(list(self._items)[:limit])

ALERTS = AlertsHub()

__all__ = ["ALERTS", "AlertsHub"]
