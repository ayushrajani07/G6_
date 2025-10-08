"""Market hours gate extraction.

Encapsulates logic deciding whether to proceed with collection or return an
early structured 'market_closed' response. Mirrors legacy behavior in
`unified_collectors.run_unified_collectors` including:
- Dynamic import of market_hours.is_market_open
- Force-open overrides (G6_FORCE_MARKET_OPEN)
- Snapshot test broadening (pytest or G6_SNAPSHOT_TEST_MODE when build_snapshots)
- Next open time & wait seconds computation
- Metrics collection_cycle_in_progress reset (best effort)
- Structured return shape with keys: status, indices_processed, have_raw,
  snapshots, snapshot_count, indices, next_open, wait_seconds

Public API:
    evaluate_market_gate(build_snapshots, metrics) -> (proceed: bool, early_result: dict | None)
"""
from __future__ import annotations
import os, datetime, logging
from typing import Any, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

__all__ = ["evaluate_market_gate"]


def evaluate_market_gate(build_snapshots: bool, metrics) -> Tuple[bool, Optional[Dict[str, Any]]]:
    # Determine market open status (permissive default on failure)
    _market_open = True
    try:  # pragma: no cover
        from src.utils import market_hours as _mh  # type: ignore
        _market_open = _mh.is_market_open(market_type="equity", session_type="regular")
    except Exception:
        _market_open = True

    # Weekend mode logic removed (reverting to strict weekday/holiday market hours only)

    force_open = os.environ.get('G6_FORCE_MARKET_OPEN','').lower() in ('1','true','yes','on')

    # Broaden bypass when snapshot building under tests
    try:  # pragma: no cover (defensive)
        if not force_open and build_snapshots:
            if ('PYTEST_CURRENT_TEST' in os.environ) or ('pytest' in __import__('sys').modules) or (os.environ.get('G6_SNAPSHOT_TEST_MODE','').lower() in ('1','true','yes','on')):
                force_open = True
    except Exception:
        pass

    if force_open or _market_open:
        disable_repeat = os.environ.get('G6_DISABLE_REPEAT_BANNERS','').lower() in ('1','true','yes','on')
        single_header_mode = os.environ.get('G6_SINGLE_HEADER_MODE','').lower() in ('1','true','yes','on')
        banner_debug = os.environ.get('G6_BANNER_DEBUG','').lower() in ('1','true','yes','on')
        sentinel = '_g6_logged_market_open'
        if single_header_mode:
            # In single header mode we always suppress duplicates regardless of disable_repeat
            if sentinel not in globals():
                logger.info("Equity market is open, starting collection")
                globals()[sentinel] = True  # type: ignore
            else:
                if banner_debug:
                    logger.debug("banner_suppressed market_open single_header_mode=1")
        else:
            if not (disable_repeat and sentinel in globals()):
                logger.info("Equity market is open, starting collection")
                globals()[sentinel] = True  # type: ignore
            elif banner_debug:
                logger.debug("banner_suppressed market_open disable_repeat=1")
        return True, None

    # Market closed path
    try:
        from src.utils.market_hours import get_next_market_open  # type: ignore
        next_open = get_next_market_open(market_type="equity", session_type="regular")
        wait_time = (next_open - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
    except Exception:
        next_open = None; wait_time = 0

    logger.info(
        "Equity market is closed. Next market open: %s%s",
        next_open,
        (f" (in {wait_time/60:.1f} minutes)" if next_open else ""),
    )
    # Emit trace via existing lightweight tracer if available
    try:  # pragma: no cover
        from src.collectors.helpers.struct_events import emit_trace_event  # type: ignore
        emit_trace_event("market_closed", next_open=str(next_open), wait_s=wait_time)  # type: ignore
    except Exception:
        try:
            # Fallback: attempt global _trace imported by unified collectors
            from src.collectors.unified_collectors import _trace  # type: ignore
            _trace("market_closed", next_open=str(next_open), wait_s=wait_time)
        except Exception:
            logger.debug("trace_event_failed_market_closed", exc_info=True)

    if metrics and hasattr(metrics, 'collection_cycle_in_progress'):
        try:
            metrics.collection_cycle_in_progress.set(0)  # type: ignore
        except Exception:
            pass

    early = {
        'status': 'market_closed',
        'indices_processed': 0,
        'have_raw': False,
        'snapshots': [] if build_snapshots else None,
        'snapshot_count': 0,
        'indices': [],
        'next_open': str(next_open) if next_open else None,
        'wait_seconds': wait_time,
    }
    return False, early
