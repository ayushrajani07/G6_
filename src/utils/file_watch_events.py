"""Simple event bus for file change notifications.

Consumers can subscribe to be notified when the runtime status or specific
panel files change. This is an optional layer on top of UnifiedDataSource's
mtime tracking and does not alter public behavior by default.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

# Event names
STATUS_FILE_CHANGED = "status_file_changed"
PANEL_FILE_CHANGED = "panel_file_changed"  # arg: panel name


class FileWatchEventBus:
    _instance: FileWatchEventBus | None = None
    _lock = threading.RLock()

    @classmethod
    def instance(cls) -> FileWatchEventBus:
        with cls._lock:
            if cls._instance is None:
                cls._instance = FileWatchEventBus()
            return cls._instance

    def __init__(self) -> None:
        self._subs: dict[str, set[Callable]] = {}
        self._lock = threading.RLock()

    def subscribe(self, event: str, callback: Callable) -> None:
        with self._lock:
            self._subs.setdefault(event, set()).add(callback)

    def unsubscribe(self, event: str, callback: Callable) -> None:
        with self._lock:
            if event in self._subs:
                self._subs[event].discard(callback)

    def publish(self, event: str, *args, **kwargs) -> None:
        with self._lock:
            cbs = list(self._subs.get(event, ()))
        for cb in cbs:
            try:
                cb(*args, **kwargs)
            except Exception:
                # best-effort: ignore subscriber exceptions
                pass
