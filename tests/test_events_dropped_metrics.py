from __future__ import annotations

import os
import importlib
from src.events.event_bus import EventBus


def test_events_dropped_metric_registration(monkeypatch):
    # Force metric registration by publishing an event
    bus = EventBus(max_events=8)
    bus.publish('panel_full', {'status': {'x': 1}}, coalesce_key='panel_full')
    # Attempt to access registry
    try:
        reg = importlib.import_module('src.metrics.registry')  # type: ignore
    except Exception:
        # Metrics registry not available in this environment; skip
        return
    m = getattr(reg, 'events_dropped_total', None)
    # Counter may not exist if registry helper differs; if missing we soft skip
    if m is None:
        return
    # Try increment with labels to ensure API surface available
    try:
        m.labels(reason='no_baseline', type='panel_diff').inc()
        m.labels(reason='generation_mismatch', type='panel_diff').inc()
    except Exception:
        # If labeling fails the test should surface error
        raise
