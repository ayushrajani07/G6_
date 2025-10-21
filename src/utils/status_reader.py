#!/usr/bin/env python3
from __future__ import annotations

"""StatusReader: unified, cached access to runtime_status.json

Backed by src.data_access.unified_source.UnifiedDataSource and offering
simple, consistent helpers for commonly accessed sections.
"""

import os
import threading
from datetime import UTC, datetime
from typing import Any, TypeVar, overload

from src.data_access.unified_source import DataSourceConfig, UnifiedDataSource

T = TypeVar("T")


class StatusReader:
    _singleton: StatusReader | None = None
    _lock = threading.RLock()

    @classmethod
    def get_instance(cls, status_path: str | None = None) -> StatusReader:
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = StatusReader(status_path)
            elif status_path:
                cls._singleton._update_path(status_path)
            return cls._singleton

    def __init__(self, status_path: str | None = None) -> None:
        self._path = self._resolve_path(status_path)
        self._uds = UnifiedDataSource()
        # Configure data source to our preferred path; keep other defaults
        cfg = DataSourceConfig(runtime_status_path=self._path)
        self._uds.reconfigure(cfg)

    def _resolve_path(self, path: str | None) -> str:
        if path:
            return path
        env_val = os.environ.get("G6_RUNTIME_STATUS")
        if not env_val:
            return "data/runtime_status.json"
        return str(env_val)

    def _update_path(self, path: str) -> None:
        self._path = path
        cfg = DataSourceConfig(runtime_status_path=self._path)
        self._uds.reconfigure(cfg)

    # ------------ Basic ------------
    def exists(self) -> bool:
        try:
            return os.path.exists(self._path)
        except Exception:
            return False

    def get_raw_status(self) -> dict[str, Any]:
        try:
            return self._uds.get_runtime_status() or {}
        except Exception:
            return {}

    # ------------ Common sections ------------
    def get_cycle_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_cycle_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {"cycle": None, "last_start": None, "last_duration": None, "success_rate": None}

    def get_indices_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_indices_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    def get_resources_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_resources_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {"cpu": None, "memory_mb": None}

    def get_provider_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_provider_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    def get_health_data(self) -> dict[str, Any]:
        try:
            d = self._uds.get_health_data() or {}
            if isinstance(d, dict):
                return d
        except Exception:
            pass
        return {}

    @overload
    def get_typed(self, path: str) -> Any: ...
    @overload
    def get_typed(self, path: str, default: T) -> T: ...
    def get_typed(self, path: str, default: Any = None) -> Any:
        """Traverse dotted path into the cached status dict.

        If any segment is missing, returns the provided default (None by default).
        No exception is raised; traversal stops at first missing key.
        """
        obj = self.get_raw_status()
        cur: Any = obj
        for part in path.split('.'):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur.get(part)
        return cur

    def get_status_age_seconds(self) -> float | None:
        try:
            st = self.get_raw_status()
            ts = st.get("timestamp") if isinstance(st, dict) else None
            if isinstance(ts, str):
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    now = datetime.now(UTC)
                    return (now - dt).total_seconds()
                except Exception:
                    pass
            if self._path and os.path.exists(self._path):
                import time as _t
                mtime = os.path.getmtime(self._path)
                return _t.time() - mtime
        except Exception:
            return None
        return None


def get_status_reader(status_path: str | None = None) -> StatusReader:
    return StatusReader.get_instance(status_path)
