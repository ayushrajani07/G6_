from __future__ import annotations

import json
from urllib import request as urllib_request

from src.events.event_bus import get_event_bus, EventBus
from src.orchestrator.catalog_http import _CatalogHandler


def test_events_stats_basic(monkeypatch, http_server_factory):
    # Use isolated bus
    bus = EventBus(max_events=32)

    def _get_bus(_max_events: int = 2048):  # signature compatibility
        return bus

    monkeypatch.setattr('src.events.event_bus.get_event_bus', _get_bus, raising=False)
    monkeypatch.setattr('src.orchestrator.catalog_http.get_event_bus', _get_bus, raising=False)

    # Publish a few events
    bus.publish('panel_full', {'status': {'a': 1}}, coalesce_key='panel_full')
    bus.publish('panel_diff', {'ops': []})
    bus.publish('followup_alert', {'alert': {'type': 'interpolation_high'}, 'severity': 'warn'})

    with http_server_factory(_CatalogHandler) as server:
        port = server.server_address[1]
        url = f'http://127.0.0.1:{port}/events/stats'
        with urllib_request.urlopen(url, timeout=5) as resp:
            body = resp.read().decode('utf-8')
            data = json.loads(body)
            assert data['latest_id'] >= 3
            assert data['backlog'] >= 2  # panel_full coalesced may reduce
            assert 'panel_full' in data['types']
            assert 'panel_diff' in data['types']
            assert 'followup_alert' in data['types']
            assert data['highwater'] >= data['backlog']
            assert data['max_events'] == 32
