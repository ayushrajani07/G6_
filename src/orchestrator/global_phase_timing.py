"""Global phase timing accumulator.

When G6_GLOBAL_PHASE_TIMING=1 we suppress per-invocation PHASE_TIMING_MERGED
logs inside unified_collectors and instead accumulate the merged phase timing
segments for each (possibly partial) invocation. At the end of the *overall*
cycle (after all per-index or batch invocations) the orchestrator emits a
single consolidated timing line.

Design goals:
  * Zero overhead when flag disabled (imports are cheap; functions early-exit)
  * Tolerate partial failures (missing or malformed dicts ignored)
  * Idempotent per-cycle reset driven by a cycle timestamp (epoch seconds)
  * Stable output ordering: descending by duration, same formatting as existing
    PHASE_TIMING_MERGED lines for consistency.

Public functions:
  reset_for_cycle(cycle_ts: int) -> None
    Clears internal state if cycle_ts differs from the active cycle.
  record_phases(phases: dict[str,float]) -> None
    Adds durations into the accumulator for the active cycle (summing values).
  emit_global(indices_total: int, logger_name: str = "collectors.unified") -> None
    Emits one log line (INFO) with prefix PHASE_TIMING_GLOBAL and clears state.

Thread-safety: current orchestrator model invokes unified collectors in the
same thread (even for parallel indices we record after each partial run).
If future parallelization requires it a simple threading.Lock can be added;
left out for performance and to avoid needless complexity now.
"""
from __future__ import annotations

import logging
import os

_ACTIVE_CYCLE_TS: int | None = None
_ACC: dict[str, float] = {}

def _enabled() -> bool:
    return os.environ.get('G6_GLOBAL_PHASE_TIMING','').lower() in ('1','true','yes','on')

def reset_for_cycle(cycle_ts: int | None) -> None:
    global _ACTIVE_CYCLE_TS, _ACC
    if not _enabled():
        return
    try:
        ts_int = int(cycle_ts) if cycle_ts is not None else 0
    except Exception:
        ts_int = 0
    if _ACTIVE_CYCLE_TS != ts_int:
        _ACTIVE_CYCLE_TS = ts_int
        _ACC.clear()

def record_phases(phases: dict[str, float] | None) -> None:
    if not _enabled() or not phases:
        return
    for k, v in phases.items():
        try:
            fv = float(v)
        except Exception:
            continue
        _ACC[k] = _ACC.get(k, 0.0) + fv

def emit_global(indices_total: int, cycle_ts: int | None, logger_name: str = 'collectors.unified') -> None:
    if not _enabled():
        return
    logger = logging.getLogger(logger_name)
    try:
        total_ph = sum(_ACC.values()) or 0.0
        parts = [
            f"{k}={v:.3f}s({(v/total_ph*100.0 if total_ph else 0.0):.1f}%)"
            for k, v in sorted(_ACC.items(), key=lambda x: -x[1])
        ]
        try:
            ts_int = int(cycle_ts or 0)
        except Exception:
            ts_int = 0
        logger.info(
            "PHASE_TIMING_GLOBAL cycle_ts=%s indices=%s %s | total=%.3fs",
            ts_int,
            indices_total,
            ' | '.join(parts),
            total_ph,
        )
    except Exception:
        logger.debug('phase_timing_global_emit_failed', exc_info=True)
    finally:
        # Always clear after emission to avoid accidental carry over
        _ACC.clear()

__all__ = ['reset_for_cycle', 'record_phases', 'emit_global']
