#!/usr/bin/env python3
"""Unified data access layer for G6.

Provides a single, cached facade to fetch data from metrics, panels JSON, and
runtime status JSON, with configurable priority and opt-in overrides.

Default priority: metrics > panels > runtime_status > logs (logs not implemented here).
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

try:
    import requests  # requests stubs present
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]


@dataclass
class DataSourceConfig:
    metrics_url: str | None = None
    runtime_status_path: str | None = None
    panels_dir: str | None = None
    cache_ttl_seconds: float = 2.0
    # New: lightweight file watching knobs
    watch_files: bool = True
    file_poll_interval: float = 0.5
    # Optional: enable cache diagnostics (hits/misses/reads)
    enable_cache_stats: bool = False

    def __post_init__(self):
        self.metrics_url = self.metrics_url or os.environ.get('G6_METRICS_URL', 'http://127.0.0.1:9108/metrics')
        self.runtime_status_path = self.runtime_status_path or os.environ.get('G6_RUNTIME_STATUS', 'data/runtime_status.json')
        self.panels_dir = self.panels_dir or os.environ.get('G6_PANELS_DIR', os.path.join('data', 'panels'))
        # Priorities: smaller means higher priority
        self.source_priority = {
            'metrics': int(os.environ.get('G6_SOURCE_PRIORITY_METRICS', '1')),
            'panels': int(os.environ.get('G6_SOURCE_PRIORITY_PANELS', '2')),
            'runtime_status': int(os.environ.get('G6_SOURCE_PRIORITY_STATUS', '3')),
            'logs': int(os.environ.get('G6_SOURCE_PRIORITY_LOGS', '4')),
        }
        self.force_source = (os.environ.get('G6_FORCE_DATA_SOURCE') or '').strip().lower()
        self.metrics_disabled = (os.environ.get('G6_DISABLE_METRICS_SOURCE') or '').strip().lower() in ('1','true','yes','on')
        # Env toggle for cache diagnostics
        if not self.enable_cache_stats:
            self.enable_cache_stats = (os.environ.get('G6_UDS_CACHE_STATS') or '').strip().lower() in ('1','true','yes','on')

    @property
    def source_order(self) -> Sequence[str]:
        order = sorted(['metrics','panels','runtime_status','logs'], key=lambda s: self.source_priority[s])
        if self.metrics_disabled and 'metrics' in order:
            order.remove('metrics')
        if self.force_source and self.force_source in order:
            order.remove(self.force_source)
            order.insert(0, self.force_source)
        return order


class _TTLCache:
    def __init__(self, ttl: float):
        self.ttl = float(ttl)
        self._data: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            val, ts = item
            if time.time() - ts <= self.ttl:
                return val
            self._data.pop(key, None)
            return None

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = (value, time.time())

    def invalidate(self, prefix: str | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._data.clear()
            else:
                for k in list(self._data.keys()):
                    if k.startswith(prefix):
                        del self._data[k]


class UnifiedDataSource:
    _singleton: UnifiedDataSource | None = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._singleton is None:
                cls._singleton = super().__new__(cls)
                cls._singleton._initialized = False
            return cls._singleton

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self.config = DataSourceConfig()
        self.cache = _TTLCache(self.config.cache_ttl_seconds)
        # Track last seen mtimes to avoid redundant reads
        self._mtimes: dict[str, float] = {}
        self._last_stat_check: float = 0.0
        self._initialized = True
        # Cache diagnostics (optional)
        self._stats: dict[str, dict[str, int]] = {
            'status': {'hits': 0, 'misses': 0, 'reads': 0},
            'panel': {'hits': 0, 'misses': 0, 'reads': 0},
            'panel_raw': {'hits': 0, 'misses': 0, 'reads': 0},
            'metrics': {'hits': 0, 'misses': 0, 'reads': 0},
        }
        # Optional: event bus for change notifications
        try:
            from src.utils.file_watch_events import PANEL_FILE_CHANGED, STATUS_FILE_CHANGED, FileWatchEventBus
            self._event_bus = FileWatchEventBus.instance()
            self._EV_STATUS = STATUS_FILE_CHANGED
            self._EV_PANEL = PANEL_FILE_CHANGED
        except Exception:
            self._event_bus = None
            self._EV_STATUS = None
            self._EV_PANEL = None

    # ----------------- Readers -----------------
    def _should_stat_now(self) -> bool:
        try:
            now = time.time()
            if not self.config.watch_files:
                return False
            # If polling interval is zero or negative, always allow stat
            try:
                if float(self.config.file_poll_interval) <= 0.0:
                    self._last_stat_check = now
                    return True
            except Exception:
                pass
            if now - self._last_stat_check >= float(self.config.file_poll_interval):
                self._last_stat_check = now
                return True
            return False
        except Exception:
            # Be conservative: allow stat on errors
            return True

    def _has_file_changed(self, path: str | None) -> bool:
        if not path:
            return False
        try:
            # Force a stat on first encounter of this path to seed the mtime
            force_stat = path not in self._mtimes
            if not force_stat and not self._should_stat_now():
                return False
            if not os.path.exists(path):
                # If previously existed, consider changed; else no-op
                prev = self._mtimes.pop(path, None)
                return prev is not None
            try:
                st = os.stat(path)
                m = getattr(st, 'st_mtime_ns', None)
                if m is None:
                    m = st.st_mtime  # fall back to seconds resolution
            except Exception:
                m = os.path.getmtime(path)
            prev = self._mtimes.get(path)
            if prev is None or m != prev:
                self._mtimes[path] = m
                return True
            return False
        except Exception:
            # On errors, assume changed to be safe
            return True

    # --------------- Stats helpers ---------------
    def _stat_inc(self, section: str, key: str, delta: int = 1) -> None:
        if not getattr(self.config, 'enable_cache_stats', False):
            return
        try:
            self._stats.setdefault(section, {})
            self._stats[section][key] = int(self._stats[section].get(key, 0)) + int(delta)
        except Exception:
            pass

    def get_cache_stats(self, reset: bool = False) -> dict[str, dict[str, int]]:
        """Return a snapshot of cache diagnostics counters.

        Keys: 'status', 'panel', 'panel_raw', 'metrics' each with {'hits','misses','reads'}.
        If reset=True, counters are zeroed after snapshot is taken.
        """
        snap = copy.deepcopy(self._stats)
        if reset:
            try:
                for sec in self._stats.values():
                    for k in list(sec.keys()):
                        sec[k] = 0
            except Exception:
                pass
        return snap
    def _read_status(self) -> dict[str, Any]:
        # Use centralized json mtime cache to minimize disk I/O on frequent polls
        try:
            from pathlib import Path as _Path

            from src.utils.csv_cache import read_json_cached as _read_json_cached  # lightweight cached reader
        except Exception:
            _read_json_cached = None  # type: ignore
            _Path = None  # type: ignore

        try:
            path = self.config.runtime_status_path
            if not path:
                return {}
            if _read_json_cached is not None and _Path is not None:
                data = _read_json_cached(_Path(path))
                return data if isinstance(data, dict) else ({})
            # Fallback direct read
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    obj = json.load(f)
                return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
        return {}

    def _read_panel(self, name: str, *, force: bool = False) -> dict[str, Any]:
        try:
            base = self.config.panels_dir
            if not base:
                return {}
            path = os.path.join(base, f"{name}.json")
            # Cached path when helper available
            try:
                from pathlib import Path as _Path

                from src.utils.csv_cache import read_json_cached as _read_json_cached
            except Exception:
                _read_json_cached = None  # type: ignore
                _Path = None  # type: ignore
            if (not force) and (_read_json_cached is not None) and (_Path is not None):
                obj = _read_json_cached(_Path(path))
            else:
                if not os.path.exists(path):
                    return {}
                with open(path, encoding='utf-8') as f:
                    obj = json.load(f)
            if isinstance(obj, dict) and 'data' in obj:
                return obj.get('data') or {}
            return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
        return {}

    def _read_panel_raw(self, name: str, *, force: bool = False) -> dict[str, Any]:
        """Read raw panel JSON without extracting the 'data' field.

        Returns the top-level dict from panels/<name>.json or empty dict on error.
        """
        try:
            base = self.config.panels_dir
            if not base:
                return {}
            path = os.path.join(base, f"{name}.json")
            try:
                from pathlib import Path as _Path

                from src.utils.csv_cache import read_json_cached as _read_json_cached
            except Exception:
                _read_json_cached = None  # type: ignore
                _Path = None  # type: ignore
            if (not force) and (_read_json_cached is not None) and (_Path is not None):
                obj = _read_json_cached(_Path(path))
                return obj if isinstance(obj, dict) else {}
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    obj = json.load(f)
                return obj if isinstance(obj, dict) else {}
        except Exception:
            pass
        return {}

    def _read_metrics(self) -> dict[str, Any]:
        """Read metrics using the centralized MetricsAdapter when available.

        Falls back to the legacy HTTP JSON endpoint (<metrics_url>/json) if the adapter
        cannot be imported or returns no data. Returned structure is normalized to a
        simple dict with optional keys used by callers:
          - 'indices': Dict[str, Any]
          - 'resources': {'cpu': float|None, 'memory_mb': float|None}
          - 'cycle': {'cycle': int|None, 'timestamp': str|None, 'elapsed': Any, 'interval': Any}
        """
        if self.config.metrics_disabled:
            return {}

        # Preferred path: MetricsAdapter (centralized, cached, fault-tolerant)
        try:
            from src.utils.metrics_adapter import get_metrics_adapter as _gma
            get_metrics_adapter: Callable[..., Any] | None = _gma
        except Exception:
            get_metrics_adapter = None

        if get_metrics_adapter is not None:
            try:
                adapter = get_metrics_adapter(self.config.metrics_url)
                pm = adapter.get_platform_metrics()
                if pm is not None:
                    # Build a compact, backward-compatible dict
                    out: dict[str, Any] = {}
                    # Resources
                    try:
                        perf = getattr(pm, 'performance', None)
                        if perf is not None:
                            out['resources'] = {
                                'cpu': getattr(perf, 'cpu_usage_percent', None),
                                'memory_mb': getattr(perf, 'memory_usage_mb', None),
                            }
                    except Exception:
                        pass
                    # Cycle info
                    try:
                        out['cycle'] = {
                            'cycle': getattr(pm, 'collection_cycle', None),
                            'timestamp': getattr(pm, 'last_updated', None),
                            'elapsed': None,
                            'interval': None,
                        }
                    except Exception:
                        pass
                    # Indices map
                    try:
                        inds = getattr(pm, 'indices', None)
                        if isinstance(inds, dict):
                            norm: dict[str, Any] = {}
                            for k, v in inds.items():
                                try:
                                    # Convert dataclass-like to dict via getattr fallbacks
                                    norm[str(k)] = {
                                        'options_processed': getattr(v, 'options_processed', None),
                                        'avg_processing_time': getattr(v, 'avg_processing_time', None),
                                        'success_rate': getattr(v, 'success_rate', None),
                                        'last_collection_time': getattr(v, 'last_collection_time', None),
                                        'atm_strike_current': getattr(v, 'atm_strike_current', None),
                                        'volatility_current': getattr(v, 'volatility_current', None),
                                        'current_cycle_legs': getattr(v, 'current_cycle_legs', None),
                                        'cumulative_legs': getattr(v, 'cumulative_legs', None),
                                        'data_quality_score': getattr(v, 'data_quality_score', None),
                                        'data_quality_issues': getattr(v, 'data_quality_issues', None),
                                    }
                                except Exception:
                                    continue
                            out['indices'] = norm
                    except Exception:
                        pass
                    return out
            except Exception:
                # Fall back to HTTP JSON below
                pass

        # Legacy fallback: read metrics JSON from dashboard endpoint
        if not requests:
            return {}
        try:
            base = (self.config.metrics_url or '').strip()
            if not base:
                return {}
            url = base.rstrip('/') + '/json'
            resp = requests.get(url, timeout=2.0)
            if resp.status_code == 200:
                return resp.json()
        except Exception:
            pass
        return {}

    # ----------------- Public API -----------------
    def get_runtime_status(self) -> dict[str, Any]:
        # If watching is enabled and file hasn't changed, return cached value when present
        path = self.config.runtime_status_path
        changed = self._has_file_changed(path)
        if not changed:
            v = self.cache.get('status')
            if v is not None:
                self._stat_inc('status', 'hits')
                return v
        # Read fresh and update cache
        # Count miss when file changed or cache empty
        self._stat_inc('status', 'misses')
        v = self._read_status()
        self._stat_inc('status', 'reads')
        self.cache.set('status', v)
        # Publish change event if applicable
        try:
            if changed and self._event_bus and self._EV_STATUS:
                self._event_bus.publish(self._EV_STATUS)
        except Exception:
            pass
        return v

    def get_panel_data(self, name: str) -> dict[str, Any]:
        key = f'p:{name}'
        # Invalidate cache if the underlying file changed
        changed = False
        try:
            base = self.config.panels_dir
            path = os.path.join(base, f"{name}.json") if base else None
            if self._has_file_changed(path):
                changed = True
                self.cache.invalidate(key)
                # Cross-invalidate corresponding raw cache so subsequent get_panel_raw sees the change
                try:
                    self.cache.invalidate(f'pr:{name}')
                except Exception:
                    pass
        except Exception:
            pass
        v = self.cache.get(key)
        if not changed and v is not None:
            self._stat_inc('panel', 'hits')
        if v is None:
            self._stat_inc('panel', 'misses')
            v = self._read_panel(name, force=changed)
            self._stat_inc('panel', 'reads')
        # Normalize in case a raw dict with top-level 'data' slipped through cache paths
        try:
            if isinstance(v, dict) and 'data' in v and isinstance(v.get('data'), dict):
                v_norm = v.get('data') or {}
                v = v_norm
        except Exception:
            pass
        # Ensure cache stores the normalized shape to avoid stale raw entries on future hits
        try:
            if isinstance(v, dict):
                self.cache.set(key, v)
        except Exception:
            pass
        # Publish change notification for panels
        try:
            if changed and self._event_bus and self._EV_PANEL:
                self._event_bus.publish(self._EV_PANEL, name)
        except Exception:
            pass
        return v

    def get_panel_raw(self, name: str) -> dict[str, Any]:
        """Get raw panel JSON including metadata like updated_at/kind.

        Cached separately from get_panel_data to avoid mixing shapes.
        """
        key = f'pr:{name}'
        # Invalidate cache if the underlying file changed
        changed = False
        try:
            base = self.config.panels_dir
            path = os.path.join(base, f"{name}.json") if base else None
            if self._has_file_changed(path):
                changed = True
                self.cache.invalidate(key)
                # Cross-invalidate corresponding normalized cache so subsequent get_panel_data sees the change
                try:
                    self.cache.invalidate(f'p:{name}')
                except Exception:
                    pass
        except Exception:
            pass
        v = self.cache.get(key)
        if not changed and v is not None:
            self._stat_inc('panel_raw', 'hits')
        if v is None or changed:
            self._stat_inc('panel_raw', 'misses')
            v = self._read_panel_raw(name, force=True)
            self._stat_inc('panel_raw', 'reads')
            self.cache.set(key, v)
        # Publish change notification for panels
        try:
            if changed and self._event_bus and self._EV_PANEL:
                self._event_bus.publish(self._EV_PANEL, name)
        except Exception:
            pass
        return v

    def get_metrics_data(self) -> dict[str, Any]:
        v = self.cache.get('metrics')
        if v is not None:
            self._stat_inc('metrics', 'hits')
            return v
        else:
            self._stat_inc('metrics', 'misses')
            v = self._read_metrics()
            self._stat_inc('metrics', 'reads')
            self.cache.set('metrics', v)
        return v

    def get_indices_data(self) -> dict[str, Any]:
        for src in self.config.source_order:
            if src == 'panels':
                d = self.get_panel_data('indices')
                if d:
                    return d
            elif src == 'runtime_status':
                s = self.get_runtime_status()
                if s and 'indices_detail' in s:
                    return s['indices_detail']
            elif src == 'metrics':
                m = self.get_metrics_data()
                if not m:
                    continue
                inds = m.get('indices')
                # Support both dict and list forms from metrics JSON
                if isinstance(inds, dict):
                    return inds
                if isinstance(inds, list):
                    out: dict[str, Any] = {}
                    for item in inds:
                        if isinstance(item, dict):
                            key = str(item.get('index') or item.get('idx') or '')
                            if key:
                                out[key] = {**item}
                    if out:
                        return out
        return {}

    def get_cycle_data(self) -> dict[str, Any]:
        for src in self.config.source_order:
            if src == 'panels':
                d = self.get_panel_data('loop')
                if d:
                    return d
            elif src == 'runtime_status':
                s = self.get_runtime_status()
                if s and 'loop' in s:
                    return s['loop']
            elif src == 'metrics':
                m = self.get_metrics_data()
                if m and 'cycle' in m:
                    return m['cycle']
        return {
            'cycle': None,
            'timestamp': datetime.now(UTC).isoformat(),
            'elapsed': None,
            'interval': None,
        }

    def get_provider_data(self) -> dict[str, Any]:
        for src in self.config.source_order:
            if src == 'panels':
                d = self.get_panel_data('provider')
                if d:
                    return d
            elif src == 'runtime_status':
                s = self.get_runtime_status()
                if s and 'provider' in s:
                    return s['provider']
        return {'name': None, 'auth': {'valid': None}, 'latency_ms': None}

    def get_resources_data(self) -> dict[str, Any]:
        for src in self.config.source_order:
            if src == 'panels':
                d = self.get_panel_data('resources')
                if d:
                    return d
            elif src == 'runtime_status':
                s = self.get_runtime_status()
                if s and 'resources' in s:
                    return s['resources']
            elif src == 'metrics':
                m = self.get_metrics_data()
                if m and 'resources' in m:
                    return m['resources']
        return {'cpu': None, 'memory_mb': None}

    def get_health_data(self) -> dict[str, Any]:
        for src in self.config.source_order:
            if src == 'panels':
                d = self.get_panel_data('health')
                if d:
                    return d
            elif src == 'runtime_status':
                s = self.get_runtime_status()
                if s and 'health' in s:
                    return s['health']
        return {}

    def get_all_indices(self) -> list[str]:
        out: set[str] = set()
        s = self.get_runtime_status()
        if s:
            if isinstance(s.get('indices'), list):
                out.update(s['indices'])
            if isinstance(s.get('indices_detail'), dict):
                out.update(s['indices_detail'].keys())
        p = self.get_panel_data('indices')
        if isinstance(p, dict):
            out.update(p.keys())
        m = self.get_metrics_data()
        if isinstance(m.get('indices'), dict):
            out.update(m['indices'].keys())
        return sorted(out)

    def get_source_status(self) -> dict[str, bool]:
        st = {'runtime_status': False, 'panels': False, 'metrics': False}
        try:
            path = self.config.runtime_status_path
            st['runtime_status'] = bool(path and os.path.exists(path))
        except Exception:
            st['runtime_status'] = False
        try:
            base = self.config.panels_dir
            st['panels'] = bool(base and os.path.isdir(base) and any(n.endswith('.json') for n in os.listdir(base)))
        except Exception:
            st['panels'] = False
        if not self.config.metrics_disabled:
            st['metrics'] = bool(self._read_metrics())
        return st

    # --------------- Admin ---------------
    def reconfigure(self, cfg: DataSourceConfig) -> None:
        with self._lock:
            self.config = cfg
            self.cache = _TTLCache(cfg.cache_ttl_seconds)
            # Reset mtime tracking when reconfiguring paths
            self._mtimes = {}
            # Reset stats when reconfiguring
            self.get_cache_stats(reset=True)

    def invalidate_cache(self, source: str | None = None) -> None:
        if source is None:
            self.cache.invalidate()
            return
        if source == 'runtime_status':
            self.cache.invalidate('status')
        elif source == 'panels':
            self.cache.invalidate('p:')
        elif source == 'metrics':
            self.cache.invalidate('metrics')


data_source = UnifiedDataSource()
