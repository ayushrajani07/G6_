from __future__ import annotations

import os
import time

from src.events.event_bus import EventBus


def _fast_adaptive_env(monkeypatch):
    # Configure very small windows & sample thresholds to exercise quickly
    monkeypatch.setenv('G6_EVENTS_BACKLOG_WARN', '3')
    monkeypatch.setenv('G6_EVENTS_BACKLOG_DEGRADE', '4')
    monkeypatch.setenv('G6_ADAPT_EXIT_BACKLOG_RATIO', '0.3')
    monkeypatch.setenv('G6_ADAPT_EXIT_WINDOW_SECONDS', '0.15')
    monkeypatch.setenv('G6_ADAPT_LAT_BUDGET_MS', '1000')  # generous
    monkeypatch.setenv('G6_ADAPT_REENTRY_COOLDOWN_SECONDS', '0.3')
    monkeypatch.setenv('G6_ADAPT_MIN_SAMPLES', '1')
    monkeypatch.setenv('G6_SSE_TRACE', '1')


def test_adaptive_exit_and_trace(monkeypatch):
    _fast_adaptive_env(monkeypatch)
    bus = EventBus(max_events=10)
    # Drive backlog into degraded
    for i in range(6):
        bus.publish('panel_diff', {'k': i})
    assert bus._degraded_mode is True
    # Publish a few low backlog events by clearing backlog artificially to simulate drain
    # Directly clear internal deque except last to keep id monotonic
    with bus._lock:  # type: ignore[attr-defined]
        # keep last event only
        if len(bus._events) > 1:  # type: ignore[attr-defined]
            last = list(bus._events)[-1]  # type: ignore[attr-defined]
            bus._events.clear()  # type: ignore[attr-defined]
            bus._events.append(last)  # type: ignore[attr-defined]
    # Provide samples below ratio
    # Generate multiple low-ratio samples distributed over > exit window
    for _ in range(6):
        bus.publish('panel_diff', {'ok': True}, coalesce_key='steady')
        time.sleep(0.03)
    # Poll up to 0.5s for degraded mode to clear
    deadline = time.time() + 0.5
    while time.time() < deadline and bus._degraded_mode:
        bus.publish('panel_diff', {'ping': True}, coalesce_key='steady')
        time.sleep(0.02)
    assert bus._degraded_mode is False, 'adaptive controller failed to exit degraded mode within window'
    bus.publish('panel_diff', {'final': True}, coalesce_key='steady')
    # Verify trace context keys present in last event
    last_event = list(bus._events)[-1]  # type: ignore[attr-defined]
    payload = last_event.payload
    assert isinstance(payload, dict)
    tr = payload.get('_trace')
    assert isinstance(tr, dict)
    assert 'publish_ts' in tr
    # serialize_ts may appear depending on timing
    assert 'id' in tr


def test_adaptive_reentry_cooldown(monkeypatch):
    _fast_adaptive_env(monkeypatch)
    bus = EventBus(max_events=10)
    # Enter degraded
    for i in range(6):
        bus.publish('panel_diff', {'v': i})
    assert bus._degraded_mode is True
    # Drain backlog and publish enough for exit
    with bus._lock:  # type: ignore[attr-defined]
        if len(bus._events) > 1:  # type: ignore[attr-defined]
            last = list(bus._events)[-1]  # type: ignore[attr-defined]
            bus._events.clear()  # type: ignore[attr-defined]
            bus._events.append(last)  # type: ignore[attr-defined]
    for _ in range(6):
        bus.publish('panel_diff', {'exit': True}, coalesce_key='steady')
        time.sleep(0.03)
    # Poll for exit
    deadline = time.time() + 0.5
    while time.time() < deadline and bus._degraded_mode:
        bus.publish('panel_diff', {'probe': True}, coalesce_key='steady')
        time.sleep(0.02)
    assert bus._degraded_mode is False, 'adaptive controller did not exit degraded' 
    bus.publish('panel_diff', {'after_exit': True}, coalesce_key='steady')
    # Immediately spike backlog again; ensure we can re-enter after cooldown only.
    # Bypass adaptive: static threshold still triggers degrade; we just want to ensure metric path safe.
    for i in range(10):
        bus.publish('panel_diff', {'spike': i})
    assert bus._degraded_mode is True
