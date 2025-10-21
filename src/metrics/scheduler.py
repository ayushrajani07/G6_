"""Scheduler-related always-on metrics.

Extracted from placeholders to isolate scheduling / gap detection concerns.
Currently includes:
  - missing_cycles (Counter): increments when a scheduled cycle is detected as skipped.

Ordering: invoked early in metrics initialization sequence (after SLA & provider failover)
so reliability chain metrics remain contiguous.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from prometheus_client import Counter

__all__ = ["init_scheduler_placeholders"]


def init_scheduler_placeholders(reg: Any, group_allowed: Callable[[str], bool]) -> None:
    """Register scheduler gap detection metrics if not already present.

    Parameters
    ----------
    reg : Metrics registry instance (dynamic attribute assignment expected)
    group_allowed : predicate for gating group tagging
    """
    log = logging.getLogger(__name__)
    log.debug("init_scheduler_placeholders: start")

    from prometheus_client import REGISTRY as _R  # defensive local import

    def _ensure(attr: str, prom_name: str, doc: str, group: str | None = None):
        if hasattr(reg, attr):
            return
        strict = False
        try:
            strict = os.getenv('G6_METRICS_STRICT_EXCEPTIONS','').lower() in {'1','true','yes','on'}
        except Exception:
            pass
        metric = None
        try:
            metric = Counter(prom_name, doc)
        except ValueError:  # duplicate
            try:
                for coll, names in getattr(_R, '_collector_to_names', {}).items():  # type: ignore[attr-defined]
                    if prom_name in names:
                        metric = coll
                        break
            except Exception:
                pass
        except Exception as e:  # unexpected
            log.error("scheduler metric create failed %s (%s): %s", attr, prom_name, e, exc_info=True)
            if strict:
                raise
        if metric is not None:
            setattr(reg, attr, metric)
            if group and group_allowed(group):
                try:
                    reg._metric_groups[attr] = group  # type: ignore[attr-defined]
                    if hasattr(reg, 'metric_group_state'):
                        reg.metric_group_state.labels(group=group).set(1)  # type: ignore[attr-defined]
                except Exception:
                    pass

    _ensure('missing_cycles', 'g6_missing_cycles_total', 'Detected missing cycles (scheduler gaps)', group='scheduler')
    log.debug("init_scheduler_placeholders: done")
