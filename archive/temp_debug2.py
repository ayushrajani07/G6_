"""Archived catalog integrity/ad-hoc event log harness.

Replaced by structured catalog + event tests. Shows dynamic env seeding
and manual dispatch cycles; preserved solely for lineage.
"""
import os, json, tempfile, socket, time, urllib.request  # noqa: F401
from src.events.event_log import dispatch  # noqa: F401
from src.orchestrator.catalog import build_catalog  # noqa: F401
from src.orchestrator.catalog_http import start_http_server_in_thread  # noqa: F401

def _wait_port(host, port, timeout=3):  # pragma: no cover
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:  # nosec B113
            s.settimeout(0.2)
            try:
                if s.connect_ex((host, port)) == 0:
                    return True
            except Exception:
                pass
        time.sleep(0.05)
    return False

def _run_demo():  # pragma: no cover
    tmp = tempfile.mkdtemp()
    status_path = os.path.join(tmp, 'runtime_status.json')
    open(status_path, 'w', encoding='utf-8').write(json.dumps({'indices': []}))
    os.environ['G6_EVENTS_LOG_PATH'] = os.path.join(tmp, 'events.log')
    os.environ['G6_CATALOG_INTEGRITY'] = '1'
    os.environ['G6_RUNTIME_STATUS_FILE'] = status_path
    for c in (1, 2, 5):
        dispatch('cycle_start', context={'cycle': c})
    cat = build_catalog(runtime_status_path=status_path)
    print('direct integrity present?', 'integrity' in cat)
    print('direct integrity:', cat.get('integrity'))
    os.environ['G6_CATALOG_HTTP_PORT'] = '9326'
    os.environ['G6_CATALOG_HTTP_REBUILD'] = '1'
    start_http_server_in_thread()
    assert _wait_port('127.0.0.1', 9326)
    payload = json.loads(urllib.request.urlopen('http://127.0.0.1:9326/catalog').read().decode())  # nosec B310
    print('http integrity present?', 'integrity' in payload)
    print('http keys', payload.keys())

if __name__ == '__main__':  # pragma: no cover
    print('Archived debug harness; rely on catalog tests now.')
    _run_demo()
