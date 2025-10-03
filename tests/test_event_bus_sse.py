from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from urllib import request as urllib_request

import pytest

from src.adaptive import followups, severity
from src.events.event_bus import EventBus, get_event_bus
from src.orchestrator.catalog_http import _CatalogHandler


def _flush_events():
    bus = get_event_bus()
    bus.clear()


def _reset_adaptive_state():
    severity._DECAY_STATE.clear()
    severity._STREAKS.clear()
    try:
        severity._TREND_BUF.clear()
    except Exception:
        pass
    severity._RULES_CACHE = None
    severity._LAST_PUBLISHED_COUNTS = None
    severity._BUS = None
    severity._BUS_FAILED = False

    followups._ALERTS.clear()
    followups._RECENT_ALERTS.clear()
    followups._LAST_EMIT.clear()
    followups._WEIGHT_EVENTS.clear()
    followups._buffers.clear()
    followups._WEIGHTS_CACHE = None
    followups._BUS = None
    followups._BUS_FAILED = False


def _patch_bus_factory(monkeypatch, *, max_events: int = 128) -> EventBus:
    bus = EventBus(max_events=max_events)

    def _get_bus(_max_events: int = 2048) -> EventBus:  # noqa: ARG001 - signature compatibility
        return bus

    monkeypatch.setattr("src.events.event_bus._GLOBAL_BUS", bus, raising=False)
    monkeypatch.setattr("src.events.event_bus.get_event_bus", _get_bus)
    monkeypatch.setattr(severity, "get_event_bus", _get_bus, raising=False)
    monkeypatch.setattr(followups, "get_event_bus", _get_bus, raising=False)
    monkeypatch.setattr(severity, "_BUS", None, raising=False)
    monkeypatch.setattr(severity, "_BUS_FAILED", False, raising=False)
    monkeypatch.setattr(severity, "_LAST_PUBLISHED_COUNTS", None, raising=False)
    monkeypatch.setattr(followups, "_BUS", None, raising=False)
    monkeypatch.setattr(followups, "_BUS_FAILED", False, raising=False)
    return bus


def test_event_bus_publish_and_coalesce():
    _flush_events()
    bus = get_event_bus()
    first = bus.publish("panel_full", {"status": {"foo": 1}}, coalesce_key="panel_full")
    time.sleep(0.01)
    second = bus.publish("panel_full", {"status": {"foo": 2}}, coalesce_key="panel_full")
    events = bus.get_since(0)
    assert [e.event_id for e in events] == [second.event_id]
    ts = second.timestamp_ist
    parsed = datetime.fromisoformat(ts)
    offset = parsed.utcoffset()
    assert offset == timedelta(hours=5, minutes=30)


def test_sse_endpoint_streams_backlog(http_server_factory):
    _flush_events()
    bus = get_event_bus()
    bus.publish("panel_full", {"status": {"foo": 42}}, coalesce_key="panel_full")
    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        url = f"http://127.0.0.1:{port}/events?types=panel_full&backlog=10"
        req = urllib_request.Request(url, headers={"Accept": "text/event-stream"})
        with urllib_request.urlopen(req, timeout=5) as resp:
            for _ in range(50):
                line = resp.readline()
                if not line:
                    break
                text = line.decode("utf-8").strip()
                if text.startswith("data:"):
                    payload = json.loads(text[5:].strip())
                    assert payload["type"] == "panel_full"
                    assert payload["payload"]["status"]["foo"] == 42
                    assert payload["timestamp_ist"].endswith("+05:30")
                    break
            else:
                pytest.fail("No SSE payload received")
    _flush_events()


def test_severity_event_published_on_state_change(monkeypatch):
    _reset_adaptive_state()
    bus = _patch_bus_factory(monkeypatch)
    bus.clear()

    alert = {"type": "interpolation_high", "interpolated_fraction": 0.9, "cycle": 5, "index": "NIFTY"}
    severity.enrich_alert(alert)

    events = bus.get_since(0)
    severity_events = [e for e in events if e.event_type == "severity_state"]
    assert severity_events, "expected severity_state event"
    payload = severity_events[-1].payload
    assert payload["alert_type"] == "interpolation_high"
    assert payload["active"] == "critical"
    assert payload["counts"]["critical"] >= 1

    counts_events = [e for e in events if e.event_type == "severity_counts"]
    assert counts_events, "expected severity_counts event"
    counts_payload = counts_events[-1].payload["counts"]
    assert counts_payload["critical"] >= 1


def test_followup_alert_event_includes_severity_counts(monkeypatch):
    _reset_adaptive_state()
    bus = _patch_bus_factory(monkeypatch)
    bus.clear()

    # Trigger interpolation guard (requires 3 consecutive breaches)
    for _ in range(3):
        followups.record_surface_metrics("BANKNIFTY", interpolated_fraction=0.85, bucket_utilization=0.9)

    events = bus.get_since(0)
    followup_events = [e for e in events if e.event_type == "followup_alert"]
    assert followup_events, "expected followup_alert event"
    payload = followup_events[-1].payload
    assert payload["index"] == "BANKNIFTY"
    assert payload["severity"] in {"warn", "critical"}
    assert "alert" in payload and payload["alert"]["type"] == "interpolation_high"
    counts = payload.get("severity_counts")
    assert counts is not None
    assert counts["warn"] + counts["critical"] >= 1
