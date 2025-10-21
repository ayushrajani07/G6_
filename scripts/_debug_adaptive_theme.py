import os
import sys
import time
import urllib.request
from pathlib import Path

# Ensure repo root on sys.path
try:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
except Exception:
    pass

from src.adaptive import logic, severity
from src.orchestrator import catalog_http as _cat_http
from src.orchestrator.catalog_http import shutdown_http_server, start_http_server_in_thread


def main():
    os.environ['PYTEST_CURRENT_TEST'] = '1'
    os.environ['G6_CATALOG_HTTP'] = '1'
    os.environ['G6_CATALOG_HTTP_PORT'] = '9393'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY'] = '1'
    os.environ['G6_ADAPTIVE_CONTROLLER'] = '1'
    os.environ['G6_ADAPTIVE_CONTROLLER_SEVERITY'] = '1'
    os.environ['G6_ADAPTIVE_SEVERITY_TREND_SMOOTH'] = '1'
    os.environ['G6_ADAPTIVE_SEVERITY_TREND_WINDOW'] = '5'
    os.environ['G6_CATALOG_HTTP_FORCE_RELOAD'] = '1'
    os.environ['G6_ADAPTIVE_ALERT_SEVERITY_RULES'] = '{"risk_delta_drift":{"warn":0.04,"critical":0.08}}'
    try:
        shutdown_http_server()
    except Exception:
        pass
    print('severity file:', getattr(severity, '__file__', None))
    print('catalog_http file:', getattr(_cat_http, '__file__', None))
    start_http_server_in_thread()
    for c in range(5):
        severity.enrich_alert({'type':'risk_delta_drift','drift_pct':0.05,'cycle':c})
        logic.evaluate_and_apply(['NIFTY'])
        time.sleep(0.01)
    with urllib.request.urlopen('http://127.0.0.1:9393/health') as _:
        pass
    with urllib.request.urlopen('http://127.0.0.1:9393/adaptive/theme') as resp:
        hdr = dict(resp.getheaders())
        body = resp.read().decode('utf-8')
    print('headers:', hdr)
    print(body)

if __name__ == '__main__':
    main()
