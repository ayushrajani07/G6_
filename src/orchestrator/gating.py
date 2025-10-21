"""Gating utilities for orchestrator loop.

Encapsulates readiness and market hours gating logic previously embedded
in `unified_main.collection_loop` and surrounding startup code.

Early slice focuses on:
  * Market open check & sleep decision helper
  * Provider readiness probe wrapper (reusable by legacy path)
  * Context update convenience functions

Future (planned):
  * Adaptive interval backoff on consecutive failures
  * Dynamic strike depth scaling triggers
  * Event bus emission for gate state changes
"""
from __future__ import annotations

import datetime as _dt
import logging
import time
from collections.abc import Callable
from typing import Any

from src.utils.env_flags import is_truthy_env  # type: ignore

from .gating_types import ProviderLike

try:
    from src.utils.market_hours import (  # type: ignore
        get_next_market_open,
        is_market_open,
        is_premarket_window,
        sleep_until_market_open,
    )
except Exception:  # pragma: no cover
    def is_market_open(*_, **__):  # type: ignore
        return True
    def get_next_market_open():  # type: ignore
        return _dt.datetime.now(_dt.UTC)
    def sleep_until_market_open(**_):  # type: ignore
        time.sleep(0.1)
    def is_premarket_window(*_, **__):  # type: ignore
        return False

logger = logging.getLogger(__name__)


def wait_for_market_open(market_type: str = "equity", session_type: str = "regular", check_interval: int = 10,
                          log_prefix: str = "[gating]") -> None:
    """Block until the next market open.

    Mirrors legacy behavior but extracted for reuse; logs a concise
    progress line every ~5 minutes (configurable via check_interval).
    """
    next_open = get_next_market_open()
    wait_secs = (next_open - _dt.datetime.now(_dt.UTC)).total_seconds()
    logger.info(f"{log_prefix} Market closed. Waiting {wait_secs/60:.1f} minutes until {next_open}")
    def _on_wait_start(dt):  # pragma: no cover (callback wiring)
        logger.info(f"{log_prefix} Waiting for market open at {dt}")
    def _on_wait_tick(rem):  # pragma: no cover
        if rem % 300 == 0:  # every 5 minutes
            logger.info(f"{log_prefix} Still waiting: {rem/60:.1f}m")
        return True
    sleep_until_market_open(
        market_type=market_type,
        session_type=session_type,
        check_interval=check_interval,
        on_wait_start=_on_wait_start,
        on_wait_tick=_on_wait_tick,
    )


def provider_readiness_probe(providers: ProviderLike | Any, symbol: str = "NIFTY", error_handler: Callable[..., Any] | None = None) -> tuple[bool, str]:
    """Perform a lightweight provider readiness probe using get_ltp.

    Parameters
    ----------
    providers: Providers facade (must expose get_ltp)
    symbol: str
        Index symbol used for probe
    error_handler: Optional[Callable]
        Error handler for structured reporting (signature loosely compatible
        with get_error_handler().handle_error)
    Returns
    -------
    (ok, reason)
    """
    try:
        ltp = providers.get_ltp(symbol)  # type: ignore[attr-defined]
        if isinstance(ltp, (int, float)) and ltp > 0:
            return True, f"LTP={ltp}"
        return False, f"Non-positive LTP={ltp}"
    except Exception as e:  # pragma: no cover
        if error_handler:
            try:
                error_handler(
                    e,
                    category=getattr(__import__('src.error_handling', fromlist=['ErrorCategory']).error_handling, 'ErrorCategory', object),  # type: ignore
                    severity=getattr(__import__('src.error_handling', fromlist=['ErrorSeverity']).error_handling, 'ErrorSeverity', object),  # type: ignore
                    component="orchestrator.gating",
                    function_name="provider_readiness_probe",
                    message="Provider readiness probe exception",
                    context={"symbol": symbol},
                )
            except Exception:
                pass
        return False, f"Exception {e}"


def should_skip_cycle_market_hours(only_during_market_hours: bool, *, log_prefix: str = "[gating]") -> bool:
    """Return True if current time is outside market hours and collection should pause."""
    if not only_during_market_hours:
        return False
    # Force-open override
    try:
        if is_truthy_env('G6_FORCE_MARKET_OPEN'):
            return False
    except Exception:
        pass
    # Weekend mode support removed: collection always suppressed outside market hours based solely on is_market_open.

    try:
        open_now = is_market_open()
    except Exception:  # pragma: no cover
        open_now = True
    if open_now:
        return False
    # If we are in the broader premarket init window (08:00–09:15 IST) allow cycles whose callers
    # will internally gate expensive collection until regular session. We log at debug for clarity.
    try:
        if is_premarket_window():  # type: ignore
            logger.debug(f"{log_prefix} Premarket window active (init-only); allowing lightweight cycle")
            return False
    except Exception:  # pragma: no cover
        pass
    logger.debug(f"{log_prefix} Market closed; cycle skipped")
    return True


def market_will_be_closed(next_interval_seconds: float) -> bool:
    """Heuristic to detect if market will be closed by next planned cycle.

    Reuses is_market_open reference time evaluation to avoid starting a cycle
    that would complete after close.
    """
    try:
        ref_time = _dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=next_interval_seconds)
        return not is_market_open(reference_time=ref_time)  # type: ignore[arg-type]
    except Exception:  # pragma: no cover
        return False

__all__ = [
    "wait_for_market_open",
    "provider_readiness_probe",
    "should_skip_cycle_market_hours",
    "market_will_be_closed",
]
