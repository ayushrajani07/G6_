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
from typing import Any, Dict
import logging

logger = logging.getLogger(__name__)

try:  # local import protective wrapper
    from src.utils.memory_pressure import MemoryPressureManager  # type: ignore
except Exception:  # pragma: no cover
    MemoryPressureManager = None  # type: ignore

__all__ = ["evaluate_memory_pressure"]

def evaluate_memory_pressure(metrics) -> Dict[str, Any]:  # pragma: no cover (thin wrapper)
    flags: Dict[str, Any] = {
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
        mp_manager = MemoryPressureManager(metrics=metrics)
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
