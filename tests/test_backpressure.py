from __future__ import annotations

import os
import time

from src.events.event_bus import EventBus


def test_backpressure_degraded_mode(monkeypatch):
    # Force small backlog and low thresholds
    monkeypatch.setenv('G6_EVENTS_BACKLOG_WARN', '2')
    monkeypatch.setenv('G6_EVENTS_BACKLOG_DEGRADE', '3')
    bus = EventBus(max_events=5)

    # Publish diff events until degraded triggers
    for i in range(5):
        bus.publish('panel_diff', {'x': i})
    # After enough events, degraded mode should be true
    assert bus._degraded_mode is True
    # Latest diff payload should be degraded marker
    # Access last event from internal deque (implementation detail OK for test)
    last_event = list(bus._events)[-1]  # type: ignore[attr-defined]
    assert isinstance(last_event.payload, dict) and last_event.payload.get('degraded') is True


def test_backpressure_metrics(monkeypatch):
    monkeypatch.setenv('G6_EVENTS_BACKLOG_WARN', '1')
    monkeypatch.setenv('G6_EVENTS_BACKLOG_DEGRADE', '2')
    bus = EventBus(max_events=4)
    # Publish two diffs (second should trigger warn + degrade)
    bus.publish('panel_diff', {'a': 1})
    bus.publish('panel_diff', {'a': 2})
    # Metrics may be lazily registered; inspect internal counters
    assert bus._degraded_mode is True
    # Ensure generation increments only on full; still zero
    assert bus._generation == 0
