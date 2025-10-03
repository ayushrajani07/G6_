import os, json, time, socket, urllib.request
from pathlib import Path

from src.orchestrator.catalog import build_catalog
from src.events.event_log import dispatch
from src.orchestrator.catalog_http import start_http_server_in_thread, shutdown_http_server

def _wait_port(host, port, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as s:
            try:
                s.settimeout(0.2)
                s.connect((host, port))
                return True
            except Exception:
                time.sleep(0.05)
    return False


def test_integrity_summary_and_http(tmp_path, monkeypatch):
    # Prepare runtime status and events
    status_path = tmp_path / 'runtime_status.json'
    status_path.write_text(json.dumps({'indices': []}), encoding='utf-8')
    monkeypatch.setenv('G6_EVENTS_LOG_PATH', str(tmp_path / 'events.log'))
    monkeypatch.setenv('G6_CATALOG_INTEGRITY', '1')
    monkeypatch.setenv('G6_RUNTIME_STATUS_FILE', str(status_path))

    # Emit some cycle events with a deliberate gap (1,2,5)
    for c in (1,2,5):
        dispatch('cycle_start', context={'cycle': c})
    cat = build_catalog(runtime_status_path=str(status_path))
    assert 'integrity' in cat
    integ = cat['integrity']
    assert integ['missing_count'] == 2
    assert integ['status'] == 'GAPS'

    # Start HTTP server
    # Allocate an ephemeral free port to guarantee a fresh server instance
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        free_port = s.getsockname()[1]
    monkeypatch.setenv('G6_CATALOG_HTTP_PORT', str(free_port))
    # Force rebuild on each HTTP /catalog request to avoid loading a previously
    # emitted catalog.json (which may have been created by an earlier test run
    # without integrity enrichment). Without this, if data/catalog.json exists
    # already the handler will just load it and the 'integrity' key will be
    # absent, causing flakiness only in full-suite runs.
    monkeypatch.setenv('G6_CATALOG_HTTP_REBUILD', '1')
    # Ensure any prior server thread from other tests is shut down so we get fresh handler logic.
    shutdown_http_server()
    start_http_server_in_thread()
    assert _wait_port('127.0.0.1', free_port)

    # Fetch catalog
    url = f'http://127.0.0.1:{free_port}/catalog'
    with urllib.request.urlopen(url) as resp:  # nosec B310 (local test)
        assert resp.status == 200
        payload = json.loads(resp.read().decode('utf-8'))
    assert 'generated_at' in payload and payload['integrity']['missing_count'] == 2

    # Health endpoint
    with urllib.request.urlopen(f'http://127.0.0.1:{free_port}/health') as resp:  # nosec B310
        assert resp.status == 200
        data = json.loads(resp.read().decode('utf-8'))
    assert data['status'] == 'ok'
