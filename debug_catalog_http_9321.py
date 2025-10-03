import os, json, time, urllib.request, tempfile, socket
from pathlib import Path
from src.events.event_log import dispatch
from src.orchestrator.catalog_http import start_http_server_in_thread
from src.orchestrator.catalog import build_catalog

TMP = tempfile.mkdtemp()
status_path = Path(TMP)/'runtime_status.json'
status_path.write_text(json.dumps({'indices': []}), encoding='utf-8')
os.environ['G6_EVENTS_LOG_PATH'] = str(Path(TMP)/'events.log')
os.environ['G6_RUNTIME_STATUS_FILE'] = str(status_path)
os.environ['G6_CATALOG_HTTP_PORT'] = '9321'
os.environ['G6_CATALOG_HTTP_REBUILD'] = '1'
for c in (1,2,5):
    dispatch('cycle_start', context={'cycle': c})
cat = build_catalog(runtime_status_path=str(status_path))
print('Direct build integrity:', cat.get('integrity'))
start_http_server_in_thread()
for _ in range(60):
    try:
        with socket.create_connection(('127.0.0.1', 9321), timeout=0.2):
            break
    except Exception:
        time.sleep(0.05)
with urllib.request.urlopen('http://127.0.0.1:9321/catalog') as resp:
    payload = json.loads(resp.read().decode('utf-8'))
print('HTTP payload keys:', list(payload.keys()))
print('HTTP integrity:', payload.get('integrity'))
print('HTTP full (trim):', json.dumps(payload)[:400])
