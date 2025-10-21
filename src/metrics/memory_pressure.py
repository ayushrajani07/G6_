"""Memory pressure & adaptive degradation metric registrations (extracted)."""
from __future__ import annotations

import logging

from prometheus_client import Counter, Gauge

logger = logging.getLogger(__name__)

def init_memory_pressure_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('memory_pressure_level', Gauge, 'g6_memory_pressure_level', 'Memory pressure ordinal level (0=normal,1=elevated,2=high,3=critical)')
    core('memory_pressure_actions', Counter, 'g6_memory_pressure_actions_total', 'Count of mitigation actions taken due to memory pressure', ['action','tier'])
    core('memory_pressure_seconds_in_level', Gauge, 'g6_memory_pressure_seconds_in_level', 'Seconds spent in current memory pressure level')
    core('memory_pressure_downgrade_pending', Gauge, 'g6_memory_pressure_downgrade_pending', 'Downgrade pending flag (1=yes,0=no)')
    core('memory_depth_scale', Gauge, 'g6_memory_depth_scale', 'Current strike depth scaling factor (0-1)')
    core('memory_per_option_metrics_enabled', Gauge, 'g6_memory_per_option_metrics_enabled', 'Per-option metrics enabled flag (1=yes,0=no)')
    core('memory_greeks_enabled', Gauge, 'g6_memory_greeks_enabled', 'Greek & IV computation enabled flag (1=yes,0=no)')
    from prometheus_client import Gauge as _G
    try:
        registry.tracemalloc_total_kb = _G('g6_tracemalloc_total_kb', 'Total allocated size reported by tracemalloc (KiB)')
    except ValueError:
        logger.debug("Metric already exists: g6_tracemalloc_total_kb")
    try:
        registry.tracemalloc_topn_kb = _G('g6_tracemalloc_topn_kb', 'Aggregated size of top-N allocation groups (KiB)')
    except ValueError:
        logger.debug("Metric already exists: g6_tracemalloc_topn_kb")
