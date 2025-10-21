#!/usr/bin/env python3
"""Lightweight retention & optional compression worker for CSV storage.

Purpose:
    Periodically (default every 6h) scan the CSV data directory and prune
    files older than the configured retention windows.

Config (JSON / dynamic lookup):
    storage: {
        "retention": {
            "days": 30,                 # General retention for option/overview CSVs (<=0 disables)
            "overview_days": 60,        # (Optional) Different window for high-level overview files
            "scan_interval_hours": 6,   # How often to run the retention sweep
            "archive_mode": "delete",  # future: "gzip" or "move" (not yet implemented)
            "min_files_to_keep": 3      # safeguard: always keep most recent N files per directory
        }
    }

Heuristics:
    - Overview files are detected by filename containing 'overview' or living in a folder named 'overview'.
    - We do not assume a strict directory hierarchy; anything *.csv qualifies.
    - A small safeguard (min_files_to_keep) prevents entire directory depletion if timestamps are skewed.

Metrics (if provided):
    metrics.retention_files_deleted_total (Counter) with labels type=option|overview

Design Notes:
    - Intentionally simple; relies on file modified time (mtime) instead of parsing dates from filenames.
    - Safe no-op when retention_days <= 0.
    - Runs as a daemon thread; exceptions are logged & swallowed (never crash main loop).
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


def _classify(path: str) -> str:
    """Best-effort classification: 'overview' or 'option'."""
    lower = path.lower()
    if 'overview' in lower:
        return 'overview'
    # Directory heuristic
    parts = [p.lower() for p in path.split(os.sep)]
    if 'overview' in parts:
        return 'overview'
    return 'option'


def _should_delete(mtime: float, cutoff: float) -> bool:
    try:
        return mtime < cutoff
    except Exception:
        return False


def _scan_and_prune(base_dir: str,
                    retention_days: int,
                    overview_days: int | None,
                    min_keep: int,
                    metrics: Any) -> tuple[int, int]:
    now = time.time()
    general_cutoff = now - retention_days * 86400 if retention_days > 0 else -1
    overview_cutoff = None
    if overview_days and overview_days > 0:
        overview_cutoff = now - overview_days * 86400
    deleted_option = 0
    deleted_overview = 0

    if retention_days <= 0 and not (overview_days and overview_days > 0):
        return 0, 0  # disabled

    for root, _dirs, files in os.walk(base_dir):
        csv_files = [f for f in files if f.lower().endswith('.csv')]
        if not csv_files:
            continue
        # Safeguard: sort files by mtime descending; preserve newest N regardless
        file_mt_pairs: list[tuple[str, float]] = []
        for f in csv_files:
            path = os.path.join(root, f)
            try:
                mt = os.path.getmtime(path)
            except Exception:
                continue
            file_mt_pairs.append((path, mt))
        file_mt_pairs.sort(key=lambda x: x[1], reverse=True)
        protected: set[str] = {p for p, _ in file_mt_pairs[:max(min_keep, 0)]}
        for path, mt in file_mt_pairs[max(min_keep, 0):]:
            ftype = _classify(path)
            cutoff = overview_cutoff if (ftype == 'overview' and overview_cutoff is not None) else general_cutoff
            if cutoff == -1:  # general retention disabled & not overview override
                continue
            if _should_delete(mt, cutoff):
                try:
                    os.remove(path)
                    if ftype == 'overview':
                        deleted_overview += 1
                    else:
                        deleted_option += 1
                except Exception as e:
                    logger.debug(f"Retention delete failed {path}: {e}")
    # Metrics
    try:
        if metrics and hasattr(metrics, 'retention_files_deleted'):  # new counter
            if deleted_option:
                metrics.retention_files_deleted.labels(type='option').inc(deleted_option)
            if deleted_overview:
                metrics.retention_files_deleted.labels(type='overview').inc(deleted_overview)
    except Exception:
        pass
    return deleted_option, deleted_overview


def start_retention_worker(base_dir: str,
                           retention_days: int,
                           overview_days: int | None = None,
                           scan_interval_hours: int = 6,
                           min_files_to_keep: int = 3,
                           metrics: Any | None = None) -> threading.Thread:
    """Start background retention daemon thread.

    Returns the thread object (already started). Safe to call even if disabled.
    """
    if retention_days <= 0 and not (overview_days and overview_days > 0):
        logger.info("Retention worker disabled (no positive retention windows).")
        dummy = threading.Thread(target=lambda: None, name="retention-disabled")
        return dummy

    def _loop() -> None:
        logger.info(
            "Retention worker started (days=%s overview_days=%s interval_h=%s base_dir=%s)",
            retention_days, overview_days, scan_interval_hours, base_dir,
        )
        while True:
            # Use timezone-aware UTC
            started = _dt.datetime.now(_dt.UTC)
            try:
                opt_del, ov_del = _scan_and_prune(
                    base_dir,
                    retention_days,
                    overview_days,
                    min_files_to_keep,
                    metrics,
                )
                if opt_del or ov_del:
                    logger.info(
                        f"Retention pruned option={opt_del} overview={ov_del} files (took {( _dt.datetime.now(_dt.UTC) - started).total_seconds():.2f}s)"
                    )
            except Exception:
                logger.exception("Retention sweep failure (continuing)")
            # Sleep with coarse granularity; allow quick disable by setting retention_days<=0 externally (not implemented yet)
            time.sleep(max(300, scan_interval_hours * 3600))

    t = threading.Thread(target=_loop, name="retention-worker", daemon=True)
    t.start()
    return t
