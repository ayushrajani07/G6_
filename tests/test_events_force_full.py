import os
import time
import json
from urllib import request, parse

import pytest

# Lightweight bespoke HTTP server bootstrap (module-scoped) intentionally remains
# separate from the shared http_server_factory to exercise handle_request() path.
# Consider refactoring later if residual exit code noise persists.

@pytest.fixture()
def catalog_server(http_server_factory):
    from src.events.event_bus import get_event_bus
    from src.orchestrator.catalog_http import _CatalogHandler  # type: ignore

    bus = get_event_bus()
    bus.publish('panel_full', { 'status': { 'foo': 1 }, '_generation': 1 })
    bus.publish('panel_diff', { 'diff': { 'changed': { 'status': { 'foo': { 'new': 2 } } } }, 'status': { 'foo': 2 } , '_generation': 1 })

    with http_server_factory(_CatalogHandler) as server:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        # small readiness sleep not strictly needed; handler ready after bind
        time.sleep(0.05)
        yield base


def _read_sse_events(url, limit=5, types=None):
    req = request.Request(url, headers={'Accept': 'text/event-stream'})
    with request.urlopen(req, timeout=5) as resp:
        events = []
        cur_data = []
        cur_type = None
        cur_id = None
        for raw in resp:
            line = raw.decode('utf-8').rstrip('\r\n')
            if line == '':
                if cur_data:
                    try:
                        payload = json.loads('\n'.join(cur_data))
                    except Exception:
                        payload = None
                    if isinstance(payload, dict):
                        if cur_type and 'type' not in payload:
                            payload['type'] = cur_type
                        if isinstance(cur_id, int):
                            payload.setdefault('sequence', cur_id)
                        if not types or payload.get('type') in types:
                            events.append(payload)
                    cur_data = []
                    cur_type = None
                    cur_id = None
                    if len(events) >= limit:
                        break
                continue
            if line.startswith(':'):
                continue
            if line.startswith('id:'):
                try:
                    cur_id = int(line[3:].strip())
                except Exception:
                    cur_id = None
                continue
            if line.startswith('event:'):
                cur_type = line[6:].strip()
                continue
            if line.startswith('data:'):
                cur_data.append(line[5:].lstrip())
                continue
        return events


def test_force_full_injection_orders_full_first(catalog_server):
    # Request both types; force_full should prepend synthetic panel_full before backlog
    base = f"{catalog_server}/events"
    q = parse.urlencode({'types': 'panel_full,panel_diff', 'force_full': '1'})
    url = f"{base}?{q}"
    evs = _read_sse_events(url, limit=3)
    assert evs, "No events returned from SSE stream"
    # First event must be panel_full synthetic injection
    assert evs[0].get('type') == 'panel_full', f"Expected first event panel_full, got {evs[0]}"
    # Subsequent may be diff or actual full depending on timing
    if len(evs) > 1:
        assert evs[1].get('type') in ('panel_diff','panel_full')


def test_force_full_injection_includes_generation(catalog_server):
    base = f"{catalog_server}/events"
    url = f"{base}?force_full=1&types=panel_full,panel_diff"
    evs = _read_sse_events(url, limit=1)
    assert evs and evs[0].get('type') == 'panel_full'
    # synthetic injection should include generation field matching payload._generation
    gen = evs[0].get('generation')
    # Earlier expectation limited to (0,1); updated logic propagates actual server generation (>=1)
    assert isinstance(gen, int) and gen >= 0, f"Unexpected generation value: {gen}"
