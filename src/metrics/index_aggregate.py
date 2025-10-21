"""Per-index aggregate metric registrations (extracted)."""
from __future__ import annotations

import logging

from prometheus_client import REGISTRY, Counter, Gauge

logger = logging.getLogger(__name__)

def init_index_aggregate_metrics(registry: MetricsRegistry) -> None:
    from prometheus_client import Counter as _C
    from prometheus_client import Gauge as _G
    try:
        registry.index_options_processed = _G('g6_index_options_processed', 'Options processed for index last cycle', ['index'])
    except ValueError:
        logger.debug("Metric already exists: g6_index_options_processed")
    try:
        registry.index_options_processed_total = _C('g6_index_options_processed_total', 'Cumulative options processed per index (monotonic)', ['index'])
    except ValueError:
        logger.debug("Metric already exists: g6_index_options_processed_total")
    core = registry._core_reg  # type: ignore[attr-defined]
    core('index_avg_processing_time', Gauge, 'g6_index_avg_processing_time_seconds', 'Average per-option processing time last cycle', ['index'])
    core('index_success_rate', Gauge, 'g6_index_success_rate_percent', 'Per-index success rate percent', ['index'])
    core('index_last_collection_unixtime', Gauge, 'g6_index_last_collection_unixtime', 'Last successful collection timestamp (unix)', ['index'])
    core('index_current_atm', Gauge, 'g6_index_current_atm_strike', 'Current ATM strike (redundant but stable label set)', ['index'])
    core('index_current_volatility', Gauge, 'g6_index_current_volatility', 'Current representative IV (e.g., ATM option)', ['index'])
    try:
        registry.metric_group_state = Gauge('g6_metric_group_state', 'Metric group activation flag', ['group'])  # type: ignore[attr-defined]
    except ValueError:
        try:
            names_map = getattr(REGISTRY, '_names_to_collectors', {})
            maybe_existing = names_map.get('g6_metric_group_state')
            if maybe_existing is not None:
                registry.metric_group_state = maybe_existing  # type: ignore[attr-defined]
        except Exception:
            pass
    registry.index_attempts_total = Counter('g6_index_attempts_total', 'Total index collection attempts (per index, resets never)', ['index'])
    registry.index_failures_total = Counter('g6_index_failures_total', 'Total index collection failures (per index, labeled by error_type)', ['index','error_type'])
    registry.index_cycle_attempts = Gauge('g6_index_cycle_attempts', 'Attempts in the most recent completed cycle (per index)', ['index'])
    registry.index_cycle_success_percent = Gauge('g6_index_cycle_success_percent', 'Success percent for the most recent completed cycle (per index)', ['index'])
