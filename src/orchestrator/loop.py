"""Execution loop abstraction for orchestrator.

Currently a thin wrapper that will later encapsulate:
  * Per-cycle timing & sleep regulation
  * Error handling & backoff policies
  * Cardinality / gating hooks
  * Event bus publication points
  * Graceful shutdown signaling
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from src.orchestrator.context import RuntimeContext
from src.utils.env_flags import is_truthy_env  # type: ignore

try:  # optional gating utilities (early slice)
    from src.orchestrator.gating import should_skip_cycle_market_hours  # type: ignore
except Exception:  # pragma: no cover
    def should_skip_cycle_market_hours(*_, **__):  # type: ignore
        return False

logger = logging.getLogger(__name__)


def run_loop(ctx: RuntimeContext, *, cycle_fn: Callable[[RuntimeContext], None], interval: float) -> None:
    """Run the main orchestration loop using provided cycle function.

    The cycle function encapsulates the legacy work previously inside the
    monolithic unified_main loop. This indirection enables unit testing and
    future pluggable behaviors (e.g., adaptive interval, partial refresh).
    """
    logger.info("Starting orchestration loop interval=%s", interval)
    # Micro-cache frequently-read environment flags at loop startup to avoid
    # repeated os.getenv calls inside the loop.
    market_hours_only = is_truthy_env('G6_LOOP_MARKET_HOURS')
    # Optional max cycles (dev/test convenience) - only counts executed (non-skipped) cycles
    # Support legacy alias G6_MAX_CYCLES (prefer new name if both present)
    try:
        max_cycles_raw = os.environ.get('G6_LOOP_MAX_CYCLES') or os.environ.get('G6_MAX_CYCLES')
    except Exception:
        max_cycles_raw = None
    max_cycles: int | None = None
    if max_cycles_raw:
        try:
            parsed = int(max_cycles_raw)
            if parsed > 0:
                max_cycles = parsed
                logger.info("[loop] Max cycles limit enabled: %s", max_cycles)
            else:
                logger.debug("[loop] Ignoring non-positive G6_LOOP_MAX_CYCLES=%s", max_cycles_raw)
        except Exception:
            logger.warning("[loop] Invalid G6_LOOP_MAX_CYCLES=%r (must be int)", max_cycles_raw)
    executed_cycles = 0
    try:
        while not ctx.shutdown:
            start = time.time()
            try:
                if market_hours_only and should_skip_cycle_market_hours(True):  # reuse gating util semantics
                    logger.debug("[loop] Skipping cycle (market closed)")
                else:
                    cycle_fn(ctx)
                    executed_cycles += 1
                    if max_cycles is not None and executed_cycles >= max_cycles:
                        logger.info("[loop] Reached max cycles (%s) -> terminating", max_cycles)
                        break
            except KeyboardInterrupt:  # direct interrupt inside cycle_fn
                logger.info("[loop] KeyboardInterrupt received inside cycle; initiating shutdown")
                ctx.shutdown = True  # type: ignore[attr-defined]
                break
            except Exception:  # noqa
                logger.exception("Cycle execution failed")
            elapsed = time.time() - start
            sleep_for = max(0.0, interval - elapsed)
            try:
                if sleep_for:
                    time.sleep(sleep_for)
            except KeyboardInterrupt:
                logger.info("[loop] KeyboardInterrupt during sleep; terminating")
                ctx.shutdown = True  # type: ignore[attr-defined]
                break
    except KeyboardInterrupt:
        logger.info("[loop] KeyboardInterrupt (outer) -> graceful shutdown")
    finally:
        logger.info("Orchestration loop terminated")

__all__ = ["run_loop"]
