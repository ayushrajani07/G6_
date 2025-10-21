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

import datetime
import importlib
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ["evaluate_market_gate"]

# Throttle for repeated "market closed" banner to avoid log spam.
# Default to once per minute, override via G6_MARKET_GATE_LOG_INTERVAL_SEC.
_CLOSED_BANNER_INTERVAL_SEC: float = float(os.environ.get("G6_MARKET_GATE_LOG_INTERVAL_SEC", "60"))
_last_closed_banner_ts: float = 0.0


def evaluate_market_gate(build_snapshots: bool, metrics: Any | None) -> tuple[bool, dict[str, Any] | None]:
    # Determine market open status (permissive default on failure)
    _market_open = True
    # Explicit force-open override for tests and controlled runs
    try:
        _force_open_env = os.environ.get('G6_FORCE_MARKET_OPEN', '').lower() in ('1','true','yes','on')
    except Exception:
        _force_open_env = False
    try:  # pragma: no cover
        _mh = importlib.import_module('src.utils.market_hours')
        _market_open = bool(getattr(_mh, 'is_market_open', lambda **k: True)(market_type="equity", session_type="regular"))
    except Exception:
        _market_open = True

    # Weekend mode logic removed (reverting to strict weekday/holiday market hours only)

    # Snapshot tests may still bypass to prevent flakiness in CI
    force_open = False
    try:  # pragma: no cover (defensive)
        if build_snapshots:
            if ('PYTEST_CURRENT_TEST' in os.environ) or ('pytest' in __import__('sys').modules) or (os.environ.get('G6_SNAPSHOT_TEST_MODE','').lower() in ('1','true','yes','on')):
                force_open = True
    except Exception:
        pass

    # Honor environment override regardless of snapshot mode
    if _force_open_env:
        force_open = True

    if force_open or _market_open:
        disable_repeat = os.environ.get('G6_DISABLE_REPEAT_BANNERS','').lower() in ('1','true','yes','on')
        single_header_mode = os.environ.get('G6_SINGLE_HEADER_MODE','').lower() in ('1','true','yes','on')
        banner_debug = os.environ.get('G6_BANNER_DEBUG','').lower() in ('1','true','yes','on')
        sentinel = '_g6_logged_market_open'
        if single_header_mode:
            # In single header mode we always suppress duplicates regardless of disable_repeat
            if sentinel not in globals():
                logger.info("Equity market is open, starting collection")
                globals()[sentinel] = True
            else:
                if banner_debug:
                    logger.debug("banner_suppressed market_open single_header_mode=1")
        else:
            if not (disable_repeat and sentinel in globals()):
                logger.info("Equity market is open, starting collection")
                globals()[sentinel] = True
            elif banner_debug:
                logger.debug("banner_suppressed market_open disable_repeat=1")
        return True, None

    # Market closed path
    try:
        _mh = importlib.import_module('src.utils.market_hours')
        get_next_market_open = _mh.get_next_market_open
        next_open = get_next_market_open(market_type="equity", session_type="regular")
        wait_time = (next_open - datetime.datetime.now(datetime.UTC)).total_seconds()
    except Exception:
        next_open = None; wait_time = 0

    # Throttled banner: emit at most once per configured interval
    global _last_closed_banner_ts
    now_ts = time.time()
    if (_last_closed_banner_ts == 0.0) or (now_ts - _last_closed_banner_ts >= _CLOSED_BANNER_INTERVAL_SEC):
        logger.info(
            "Equity market is closed. Next market open: %s%s",
            next_open,
            (f" (in {wait_time/60:.1f} minutes)" if next_open else ""),
        )
        _last_closed_banner_ts = now_ts
    # Emit trace via existing lightweight tracer if available
    try:  # pragma: no cover
        _se = importlib.import_module('src.collectors.helpers.struct_events')
        emit_trace_event = getattr(_se, 'emit_trace_event', None)
        if callable(emit_trace_event):
            emit_trace_event("market_closed", next_open=str(next_open), wait_s=wait_time)
    except Exception:
        try:
            # Fallback: attempt global _trace imported by unified collectors
            _uc = importlib.import_module('src.collectors.unified_collectors')
            _trace = getattr(_uc, '_trace', None)
            if callable(_trace):
                _trace("market_closed", next_open=str(next_open), wait_s=wait_time)
        except Exception:
            logger.debug("trace_event_failed_market_closed", exc_info=True)

    if metrics and hasattr(metrics, 'collection_cycle_in_progress'):
        try:
            metrics.collection_cycle_in_progress.set(0)
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
