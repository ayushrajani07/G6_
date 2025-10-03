import os, json, time, urllib.request
from src.adaptive import severity, logic
from src.orchestrator.catalog_http import start_http_server_in_thread
os.environ['G6_CATALOG_HTTP']='1'
os.environ['G6_CATALOG_HTTP_PORT']='9322'
os.environ['G6_ADAPTIVE_ALERT_SEVERITY']='1'
os.environ['G6_ADAPTIVE_CONTROLLER']='1'
os.environ['G6_ADAPTIVE_CONTROLLER_SEVERITY']='1'
os.environ['G6_ADAPTIVE_SEVERITY_TREND_SMOOTH']='1'
os.environ['G6_ADAPTIVE_SEVERITY_TREND_WINDOW']='5'
os.environ['G6_ADAPTIVE_ALERT_SEVERITY_RULES']='{"risk_delta_drift":{"warn":0.04,"critical":0.08}}'
start_http_server_in_thread()
for c in range(5):
    severity.enrich_alert({'type':'risk_delta_drift','drift_pct':0.05,'cycle':c})
    logic.evaluate_and_apply(['NIFTY'])
    time.sleep(0.01)
with urllib.request.urlopen('http://127.0.0.1:9322/adaptive/theme') as resp:
    data = json.loads(resp.read().decode())
print('http window', data.get('trend',{}).get('window'))
