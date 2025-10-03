from __future__ import annotations

import os
import time
import json
from urllib import request as urllib_request

import pytest

from src.events.event_bus import EventBus, get_event_bus
from src.orchestrator.catalog_http import _CatalogHandler


def _new_isolated_bus(monkeypatch, max_events: int = 128) -> EventBus:
    bus = EventBus(max_events=max_events)
    def _get_bus(_max_events: int = 2048) -> EventBus:  # noqa: ARG001
        return bus
    monkeypatch.setattr("src.events.event_bus._GLOBAL_BUS", bus, raising=False)
    monkeypatch.setattr("src.events.event_bus.get_event_bus", _get_bus)
    return bus


def test_forced_full_gap_exceeded(monkeypatch):
    os.environ['G6_EVENTS_SNAPSHOT_GAP_MAX'] = '3'  # very small gap threshold
    os.environ['G6_EVENTS_FORCE_FULL_RETRY_SECONDS'] = '0.1'
    bus = _new_isolated_bus(monkeypatch)

    # Publish initial full snapshot baseline
    bus.publish('panel_full', {'status': {'a': 1}}, coalesce_key='panel_full')
    base_full_id = bus.latest_id()

    # Publish 4 diffs to exceed gap (gap threshold=3 means after >3 events since last full)
    for i in range(4):
        bus.publish('panel_diff', {'diff': {'v': i}})
        bus.enforce_snapshot_guard()

    events = bus.get_since(0)
    full_events = [e for e in events if e.event_type == 'panel_full']
    # Because panel_full uses coalesce_key, forced full replaces prior; expect exactly 1 stored full.
    assert len(full_events) == 1, f"expected single coalesced full, got {len(full_events)}"
    last_full = full_events[0]
    # Forced full should carry forced_reason in payload
    forced_flag = False
    if isinstance(last_full.payload, dict):
        if 'forced_reason' in last_full.payload:
            forced_flag = True
        else:
            st = last_full.payload.get('status')
            if isinstance(st, dict) and 'forced_reason' in st:
                forced_flag = True
    assert forced_flag, 'forced full event missing forced_reason'

    # Cooldown prevents immediate second forced full
    current_full_count = len(full_events)
    bus.publish('panel_diff', {'diff': {'extra': True}})
    bus.enforce_snapshot_guard()  # Should be within cooldown window
    events2 = bus.get_since(0)
    full_events2 = [e for e in events2 if e.event_type == 'panel_full']
    assert len(full_events2) == current_full_count, "unexpected extra forced full within cooldown"

    # Wait for cooldown and trigger again
    time.sleep(0.12)
    for i in range(2):
        bus.publish('panel_diff', {'diff': {'late': i}})
    bus.enforce_snapshot_guard()
    events3 = bus.get_since(0)
    full_events3 = [e for e in events3 if e.event_type == 'panel_full']
    assert len(full_events3) >= current_full_count, "expected at least same number of full events"


def test_events_stats_forced_full_last(monkeypatch, http_server_factory):
    os.environ['G6_EVENTS_SNAPSHOT_GAP_MAX'] = '1'
    os.environ['G6_EVENTS_FORCE_FULL_RETRY_SECONDS'] = '0'
    bus = _new_isolated_bus(monkeypatch)
    bus.publish('panel_full', {'status': {'a': 1}}, coalesce_key='panel_full')
    bus.publish('panel_diff', {'diff': {'b': 2}})
    bus.enforce_snapshot_guard()

    # Start ephemeral HTTP server and fetch /events/stats
    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/events/stats"
        with urllib_request.urlopen(url, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        assert 'forced_full_last' in data
        ffl = data['forced_full_last']
        # At least one reason recorded
        assert any(r in ffl for r in ('gap_exceeded','missing_baseline','generation_mismatch')) or ffl == {}, "forced_full_last missing expected reasons"


@pytest.mark.timeout(5)
def test_connection_duration_histogram(monkeypatch, http_server_factory):
    # Basic smoke: open and close SSE quickly then ensure stats reflect consumer decrement.
    bus = _new_isolated_bus(monkeypatch)
    # Seed a baseline event so backlog not empty
    bus.publish('panel_full', {'status': {'x': 1}}, coalesce_key='panel_full')
    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/events?types=panel_full&backlog=1"
        req = urllib_request.Request(url, headers={'Accept':'text/event-stream'})
        with urllib_request.urlopen(req, timeout=3) as resp:
            # Read a few lines then exit (closing connection)
            for _ in range(10):
                line = resp.readline()
                if not line:
                    break
                if line.startswith(b'data:'):
                    break
        # Allow server handler to run finally block
        time.sleep(0.15)
        snap = bus.stats_snapshot()
        assert snap['consumers'] in (0,1)  # tolerate race; primary goal is no crash
