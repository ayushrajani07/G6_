"""Tracemalloc-based memory tracing hooks for optional diagnostics.

Enable via environment variables:
  - G6_ENABLE_TRACEMALLOC=1           -> start tracemalloc and collect stats per cycle
  - G6_TRACEMALLOC_TOPN=10            -> number of top allocation groups to aggregate (by traceback)
  - G6_TRACEMALLOC_WRITE_SNAPSHOTS=0  -> when 1, write snapshot files to G6_TRACEMALLOC_SNAPSHOT_DIR
  - G6_TRACEMALLOC_SNAPSHOT_DIR=logs/mem

Metrics (if provided):
  - g6_tracemalloc_total_kb
  - g6_tracemalloc_topn_kb (aggregated sum of TOPN groups)

Safe to import even if tracemalloc not available; no-ops when disabled.
"""
from __future__ import annotations

import os
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import tracemalloc  # type: ignore
except Exception:  # pragma: no cover
    tracemalloc = None  # type: ignore


class MemoryTracer:
    def __init__(self, topn: Optional[int] = None, snapshot_dir: Optional[str] = None, write_snapshots: Optional[bool] = None):
        self.enabled = os.environ.get('G6_ENABLE_TRACEMALLOC', '0').lower() in ('1','true','yes','on') and bool(tracemalloc)
        self.topn = int(os.environ.get('G6_TRACEMALLOC_TOPN', str(topn if topn is not None else 10)) or '10')
        self.snapshot_dir = os.environ.get('G6_TRACEMALLOC_SNAPSHOT_DIR', snapshot_dir or 'logs/mem')
        self.write_snapshots = os.environ.get('G6_TRACEMALLOC_WRITE_SNAPSHOTS', '0').lower() in ('1','true','yes','on') if write_snapshots is None else bool(write_snapshots)
        self._started = False

    def ensure_started(self):
        if not self.enabled or not tracemalloc:
            return False
        if not self._started:
            try:
                tracemalloc.start()
                self._started = True
                logger.info("Tracemalloc enabled (topn=%s, write_snapshots=%s)", self.topn, self.write_snapshots)
            except Exception:
                logger.debug("Failed to start tracemalloc", exc_info=True)
                self.enabled = False
                return False
        return True

    def sample(self, metrics: Any | None = None):
        """Capture a snapshot and emit lightweight metrics. Optionally write snapshot to disk."""
        if not self.enabled or not tracemalloc or not self._started:
            return
        try:
            snapshot = tracemalloc.take_snapshot()
            stats = snapshot.statistics('traceback')  # group by traceback
            topn = stats[: max(0, self.topn)] if self.topn > 0 else []
            # Total and TOPN aggregated size in KiB
            total_kb = sum(stat.size for stat in stats) / 1024.0 if stats else 0.0
            topn_kb = sum(stat.size for stat in topn) / 1024.0 if topn else 0.0
            if metrics:
                try:
                    if hasattr(metrics, 'tracemalloc_total_kb'):
                        metrics.tracemalloc_total_kb.set(total_kb)
                except Exception:
                    pass
                try:
                    if hasattr(metrics, 'tracemalloc_topn_kb'):
                        metrics.tracemalloc_topn_kb.set(topn_kb)
                except Exception:
                    pass
            if self.write_snapshots:
                try:
                    os.makedirs(self.snapshot_dir, exist_ok=True)
                    # Minimal, bounded text file with top traces
                    fname = os.path.join(self.snapshot_dir, 'snapshot_top.txt')
                    with open(fname, 'w', encoding='utf-8') as f:
                        f.write(f"TOTAL_KB={total_kb:.1f} TOP{self.topn}_KB={topn_kb:.1f}\n")
                        for i, stat in enumerate(topn, start=1):
                            f.write(f"[{i}] {stat.size/1024.0:.1f} KiB\n")
                            # include compact traceback (last 3 frames)
                            frames = stat.traceback.format()[-3:]
                            for fr in frames:
                                f.write(f"    {fr}\n")
                except Exception:
                    logger.debug("Failed writing tracemalloc snapshot", exc_info=True)
        except Exception:
            logger.debug("Tracemalloc sample failed", exc_info=True)


_GLOBAL_TRACER: MemoryTracer | None = None


def get_tracer() -> MemoryTracer:
    global _GLOBAL_TRACER  # noqa: PLW0603
    if _GLOBAL_TRACER is None:
        _GLOBAL_TRACER = MemoryTracer()
    return _GLOBAL_TRACER


__all__ = ["MemoryTracer", "get_tracer"]
