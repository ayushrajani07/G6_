import os, time, http.client, threading
os.environ['G6_SSE_HTTP']='1'
os.environ['G6_SUMMARY_METRICS_HTTP']='1'
from scripts.summary.plugins.sse import SSEPublisher
import scripts.summary.metrics_server as ms
print('metrics_server_file=', getattr(ms, '__file__', None))
from scripts.summary.unified_loop import UnifiedLoop
pub = SSEPublisher(diff=True)
loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.05)
t = threading.Thread(target=lambda: loop.run(cycles=2), daemon=True)
t.start()
time.sleep(0.6)
conn = http.client.HTTPConnection('127.0.0.1', 9325, timeout=2)
conn.request('GET','/metrics')
resp = conn.getresponse()
body = resp.read().decode('utf-8','ignore')
print('STATUS=', resp.status)
print('HDR_X_G6=', resp.getheader('X-G6-Summary-Metrics'))
print('HDR_Server=', resp.getheader('Server'))
print('HEAD=', body.splitlines()[:20])
print('HAS_SSE_ACTIVE=', 'g6_sse_http_active_connections' in body)
print('HAS_SSE_TOTAL=', 'g6_sse_http_connections_total' in body)
print('LEN=', len(body))
conn.close()
