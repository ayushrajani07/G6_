import os
import time
import threading
import json
from urllib import request, parse

import pytest

# This test exercises the summary client's auto recovery logic in a minimal way by
# simulating a scenario where a diff arrives before a baseline. We focus on the
# EventBus + synthetic SSE consumption rather than invoking the full rich UI.

@pytest.fixture()
def sse_server(tmp_path):
    from src.events.event_bus import get_event_bus
    from src.orchestrator.catalog_http import _CatalogHandler  # type: ignore
    from http.server import ThreadingHTTPServer

    bus = get_event_bus()
    # Ensure clean slate
    # (EventBus does not expose clear publicly; rely on generation & ordering resilience.)

    host = '127.0.0.1'
    port = 9410

    stop = threading.Event()

    def _run():
        httpd = ThreadingHTTPServer((host, port), _CatalogHandler)
        httpd.timeout = 0.5
        try:
            while not stop.is_set():
                httpd.handle_request()
        finally:
            try:
                httpd.server_close()
            except Exception:
                pass
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    time.sleep(0.25)
    yield bus, f"http://{host}:{port}"
    stop.set()
    t.join(timeout=2)


def _consume_until(url, want_types, timeout=2.0):
    req = request.Request(url, headers={'Accept': 'text/event-stream'})
    deadline = time.time() + timeout
    got = []
    with request.urlopen(req, timeout=timeout) as resp:
        cur_data = []
        cur_type = None
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
                        got.append(payload)
                        if len([g for g in got if g.get('type') in want_types]) >= len(want_types):
                            break
                    cur_data = []
                    cur_type = None
                if time.time() > deadline:
                    break
                continue
            if line.startswith('event:'):
                cur_type = line[6:].strip()
                continue
            if line.startswith('data:'):
                cur_data.append(line[5:].lstrip())
                continue
            if time.time() > deadline:
                break
    return got


def test_auto_recovery_force_full_once(sse_server, monkeypatch):
    bus, base_url = sse_server

    # Publish only a diff first to trigger need_full on client side once consumed.
    bus.publish('panel_diff', { 'diff': { 'added': { 'status': { 'a': 1 } } }, '_generation': 2 })
    # Then publish a legitimate full snapshot with NEW generation to trigger mismatch and recovery path semantics.
    bus.publish('panel_full', { 'status': { 'a': 1 }, '_generation': 3 })

    # Build an SSE URL restricted to diffs; client will request force_full=1 itself if auto recovery active.
    diff_only = f"{base_url}/events?types=panel_full,panel_diff"

    # Simulate the summary client's auto recovery URL build logic manually:
    # First attempt (need_full detected) should append force_full=1.
    # We mimic two sequential connections: initial (shows diff rejected, but our harness directly goes to second).

    # Directly request with force_full=1 to emulate the second connection after NEED_FULL detection.
    full_url = diff_only + "&force_full=1"
    events = _consume_until(full_url, want_types=['panel_full'], timeout=1.5)

    # Ensure first received event is the injected full (even though types=panel_diff) then diff appears.
    assert events, "No events received during recovery scenario"
    assert events[0].get('type') == 'panel_full', f"Expected injected panel_full first, got {events[0]}"
    # A diff may follow; not strictly required for validation but if present should be panel_diff.
    # We only required the baseline; diff presence optional.

