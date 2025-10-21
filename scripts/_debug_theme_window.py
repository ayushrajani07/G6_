import json
import os
import sys
import time
import urllib.request
from pathlib import Path

# Ensure repository root on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.adaptive import logic, severity
from src.orchestrator.catalog_http import shutdown_http_server, start_http_server_in_thread


def main():
    os.environ['G6_CATALOG_HTTP']='1'
    os.environ['G6_CATALOG_HTTP_PORT']='9394'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY']='1'
    os.environ['G6_ADAPTIVE_CONTROLLER']='1'
    os.environ['G6_ADAPTIVE_CONTROLLER_SEVERITY']='1'
    os.environ['G6_ADAPTIVE_SEVERITY_TREND_SMOOTH']='1'
    os.environ['G6_ADAPTIVE_SEVERITY_TREND_WINDOW']='5'
    os.environ['G6_CATALOG_HTTP_FORCE_RELOAD']='1'
    try:
        shutdown_http_server()
    except Exception:
        pass
    start_http_server_in_thread()
    for c in range(5):
        severity.enrich_alert({'type':'risk_delta_drift','drift_pct':0.05,'cycle':c})
        logic.evaluate_and_apply(['NIFTY'])
        time.sleep(0.01)
    with urllib.request.urlopen('http://127.0.0.1:9394/adaptive/theme') as resp:
        body = resp.read().decode('utf-8')
    print('raw:', body)
    data = json.loads(body)
    trend = data.get('trend')
    print('trend_type:', type(trend).__name__, 'value:', trend)
    w = trend.get('window') if isinstance(trend, dict) else None
    print('window_field:', w)
    print('smoothing_env:', data.get('smoothing_env'))
    shutdown_http_server()

if __name__ == '__main__':
    main()
