import os, json, tempfile, socket, time, urllib.request
from src.events.event_log import dispatch
from src.orchestrator.catalog import build_catalog
from src.orchestrator.catalog_http import start_http_server_in_thread

def wait_port(host, port, timeout=3):
    end=time.time()+timeout
    while time.time()<end:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                if s.connect_ex((host,port))==0:
                    return True
            except Exception: pass
        time.sleep(0.05)
    return False

tmp=tempfile.mkdtemp()
status_path=os.path.join(tmp,'runtime_status.json')
open(status_path,'w').write(json.dumps({'indices': []}))
os.environ['G6_EVENTS_LOG_PATH']=os.path.join(tmp,'events.log')
os.environ['G6_CATALOG_INTEGRITY']='1'
os.environ['G6_RUNTIME_STATUS_FILE']=status_path
for c in (1,2,5):
    dispatch('cycle_start', context={'cycle': c})
cat=build_catalog(runtime_status_path=status_path)
print('direct integrity present?', 'integrity' in cat)
print('direct integrity:', cat.get('integrity'))
os.environ['G6_CATALOG_HTTP_PORT']='9326'
os.environ['G6_CATALOG_HTTP_REBUILD']='1'
start_http_server_in_thread()
assert wait_port('127.0.0.1',9326)
import urllib.request
payload=json.loads(urllib.request.urlopen('http://127.0.0.1:9326/catalog').read().decode())
print('http integrity present?', 'integrity' in payload)
print('http keys', payload.keys())
