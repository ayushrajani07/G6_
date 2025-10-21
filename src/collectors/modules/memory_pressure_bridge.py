"""Memory pressure management bridge extraction.

Wraps initialization and evaluation of MemoryPressureManager, returning a
serializable flags dict identical to legacy inline _evaluate_memory_pressure.

Public API:
    evaluate_memory_pressure(metrics) -> dict

Returns flags:
    {
      'reduce_depth': bool,
      'skip_greeks': bool,
      'slow_cycles': bool,
      'drop_per_option_metrics': bool,
      'depth_scale': float,
      'manager': MemoryPressureManager | None   # included for advanced callers
    }

Best-effort: exceptions swallowed; returns safe defaults.
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

try:  # local import protective wrapper
    from src.utils.memory_pressure import MemoryPressureManager  # type: ignore
except Exception:  # pragma: no cover
    MemoryPressureManager = None  # type: ignore

__all__ = ["evaluate_memory_pressure"]

# Simple module-level TTL cache so callers that evaluate memory pressure frequently
# (hot paths) don't repeatedly instantiate MemoryPressureManager. Disabled by
# default; enable with G6_MEMORY_PRESSURE_TTL_MS or G6_MEMORY_PRESSURE_TTL_SEC.
_MP_CACHE_MANAGER = None
_MP_CACHE_TS = 0.0

def _mp_cache_ttl_seconds() -> float:
    try:
        ms = os.environ.get('G6_MEMORY_PRESSURE_TTL_MS')
        if ms is not None:
            return max(0.0, float(ms) / 1000.0)
        s = os.environ.get('G6_MEMORY_PRESSURE_TTL_SEC')
        if s is not None:
            return max(0.0, float(s))
    except Exception:
        pass
    return 0.0

def evaluate_memory_pressure(metrics) -> dict[str, Any]:  # pragma: no cover (thin wrapper)
    flags: dict[str, Any] = {
        'reduce_depth': False,
        'skip_greeks': False,
        'slow_cycles': False,
        'drop_per_option_metrics': False,
        'depth_scale': 1.0,
        'manager': None,
    }
    try:
        if MemoryPressureManager is None:
            return flags
        # Check module-level TTL cache first
        ttl = _mp_cache_ttl_seconds()
        global _MP_CACHE_MANAGER, _MP_CACHE_TS
        mp_manager = None
        if ttl and _MP_CACHE_MANAGER is not None and (time.time() - _MP_CACHE_TS) < ttl:
            mp_manager = _MP_CACHE_MANAGER
            # update metrics reference in case caller provides a metrics object
            try:
                mp_manager.metrics = metrics
            except Exception:
                pass
            logger.debug('memory_pressure_cache_hit')
        else:
            mp_manager = MemoryPressureManager(metrics=metrics)
            if ttl:
                _MP_CACHE_MANAGER = mp_manager
                _MP_CACHE_TS = time.time()
        tier = mp_manager.evaluate()
        flags['manager'] = mp_manager
        flags['depth_scale'] = getattr(mp_manager, 'depth_scale', 1.0)
        act = getattr(mp_manager, 'active_flags', {})
        for k in ('reduce_depth','skip_greeks','slow_cycles','drop_per_option_metrics'):
            flags[k] = bool(act.get(k, False))
        if flags['slow_cycles']:
            logger.debug(f"Memory pressure slow_cycles active (tier={getattr(tier,'name',None)})")
    except Exception:
        logger.debug('memory_pressure_bridge_failed', exc_info=True)
    return flags
