"""Panels integrity monitoring utilities.

Periodically verifies panel manifest hashes and emits Prometheus metrics.

Environment:
  G6_PANELS_INTEGRITY_MONITOR=1      Enable background thread monitor.
  G6_PANELS_INTEGRITY_INTERVAL=60    Interval seconds between checks (default 300).
  G6_PANELS_DIR=...                  Panels directory (default data/panels).
  G6_PANELS_INTEGRITY_STRICT=1       If set, log at warning level when mismatch detected (else info).

Metrics (added to existing registry):
  g6_panels_integrity_last_run_unixtime   Gauge - UNIX time of last completed run.
  g6_panels_integrity_mismatches_total    Counter - cumulative mismatches detected.
  g6_panels_integrity_last_mismatch_count Gauge - number of mismatching panels in last run.
  g6_panels_integrity_ok                  Gauge - 1 if last run had zero mismatches else 0.

Public API:
  run_integrity_check_once(panels_dir: str) -> dict
  start_panels_integrity_monitor(panels_dir: Optional[str] = None) -> None

Thread is daemonized and idempotent (subsequent calls return early if already running).
"""
from __future__ import annotations

import logging
import os
import threading
import time

from .validate import verify_manifest_hashes  # reuses existing helper

try:
    from src.metrics import get_metrics  # facade import
except Exception:  # pragma: no cover
    get_metrics = None  # type: ignore

logger = logging.getLogger(__name__)

_MONITOR_THREAD: threading.Thread | None = None
_STOP_EVENT: threading.Event | None = None

# Metric names
_METRIC_LAST_RUN = 'g6_panels_integrity_last_run_unixtime'
_METRIC_MISMATCHES_TOTAL = 'g6_panels_integrity_mismatches_total'
_METRIC_LAST_MISMATCH_COUNT = 'g6_panels_integrity_last_mismatch_count'
_METRIC_OK = 'g6_panels_integrity_ok'
_METRIC_CHECKS_TOTAL = 'g6_panels_integrity_checks_total'
_METRIC_FAILURES_TOTAL = 'g6_panels_integrity_failures_total'


def _ensure_metrics():
    if get_metrics is None:
        return None
    m = get_metrics()
    # Lazy register if absent (idempotent)
    if not hasattr(m, _METRIC_LAST_RUN):
        from prometheus_client import Counter, Gauge  # type: ignore
        try:
            setattr(m, _METRIC_LAST_RUN, Gauge(_METRIC_LAST_RUN, 'Panels integrity last run unixtime'))
            setattr(m, _METRIC_MISMATCHES_TOTAL, Counter(_METRIC_MISMATCHES_TOTAL, 'Panels integrity mismatches total'))
            setattr(m, _METRIC_LAST_MISMATCH_COUNT, Gauge(_METRIC_LAST_MISMATCH_COUNT, 'Panels integrity last mismatch count'))
            setattr(m, _METRIC_OK, Gauge(_METRIC_OK, 'Panels integrity last run OK (1/0)'))
            # Counters used by Grafana dashboard
            setattr(m, _METRIC_CHECKS_TOTAL, Counter(_METRIC_CHECKS_TOTAL, 'Total panel integrity checks run'))
            setattr(m, _METRIC_FAILURES_TOTAL, Counter(_METRIC_FAILURES_TOTAL, 'Total panel integrity check failures'))
        except Exception:  # pragma: no cover
            logger.debug('integrity_monitor: metric registration failed', exc_info=True)
    return m


def run_integrity_check_once(panels_dir: str | None = None) -> dict[str, int]:
    """Run a single integrity verification pass.

    Returns mapping of panel filename -> mismatch count (always 1 per bad panel)
    plus aggregate keys: _total_mismatches, _ok (1/0) for convenience.
    """
    panels_dir = panels_dir or os.environ.get('G6_PANELS_DIR', 'data/panels')
    mismatches = verify_manifest_hashes(panels_dir) or {}
    count = len(mismatches)
    m = _ensure_metrics()
    ts = int(time.time())
    if m:
        try:
            getattr(m, _METRIC_LAST_RUN).set(ts)  # type: ignore[attr-defined]
            getattr(m, _METRIC_LAST_MISMATCH_COUNT).set(count)  # type: ignore[attr-defined]
            getattr(m, _METRIC_OK).set(1 if count == 0 else 0)  # type: ignore[attr-defined]
            # Always count a check run
            try:
                getattr(m, _METRIC_CHECKS_TOTAL).inc()  # type: ignore[attr-defined]
            except Exception:
                pass
            if count:
                getattr(m, _METRIC_MISMATCHES_TOTAL).inc(count)  # type: ignore[attr-defined]
                try:
                    getattr(m, _METRIC_FAILURES_TOTAL).inc(count)  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:  # pragma: no cover
            logger.debug('integrity_monitor: metric update failed', exc_info=True)
    strict = os.environ.get('G6_PANELS_INTEGRITY_STRICT','').lower() in ('1','true','yes','on')
    if count:
        log_fn = logger.warning if strict else logger.info
        log_fn('Panels integrity mismatches: %s (dir=%s)', count, panels_dir)
    else:
        logger.debug('Panels integrity OK (dir=%s)', panels_dir)
    result = {k:1 for k in mismatches.keys()}
    result['_total_mismatches'] = count
    result['_ok'] = 1 if count == 0 else 0
    return result


def start_panels_integrity_monitor(panels_dir: str | None = None) -> None:
    """Start background integrity monitor if enabled by env.

    Safe to call multiple times; only first call starts thread.
    """
    global _MONITOR_THREAD, _STOP_EVENT
    if os.environ.get('G6_PANELS_INTEGRITY_MONITOR','').lower() not in ('1','true','yes','on'):
        return
    if _MONITOR_THREAD and _MONITOR_THREAD.is_alive():
        return
    panels_dir = panels_dir or os.environ.get('G6_PANELS_DIR', 'data/panels')
    interval = float(os.environ.get('G6_PANELS_INTEGRITY_INTERVAL','300'))
    stop_event = threading.Event()
    _STOP_EVENT = stop_event

    def _loop():
        # Initial small delay to allow panels to be emitted at startup
        try:
            time.sleep(min(5.0, interval/2.0))
        except Exception:
            pass
        while not stop_event.is_set():
            try:
                run_integrity_check_once(panels_dir)
            except Exception:
                logger.exception('integrity_monitor: run failed')
            try:
                stop_event.wait(interval)
            except Exception:
                # fallback sleep
                time.sleep(interval)

    t = threading.Thread(target=_loop, name='g6-panels-integrity-monitor', daemon=True)
    t.start()
    _MONITOR_THREAD = t


__all__ = ['run_integrity_check_once', 'start_panels_integrity_monitor']
