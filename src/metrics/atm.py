"""ATM collection timing metric registrations (extracted)."""
from __future__ import annotations

from prometheus_client import Gauge


def init_atm_metrics(registry: MetricsRegistry) -> None:
    core = registry._core_reg  # type: ignore[attr-defined]
    core('atm_batch_time', Gauge, 'g6_atm_batch_time_seconds', 'Elapsed wall time to collect ATM option batch', ['index'])
    core('atm_avg_option_time', Gauge, 'g6_atm_avg_option_time_seconds', 'Average per-option processing time within ATM batch', ['index'])
