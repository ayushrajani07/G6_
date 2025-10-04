import http.client, time, os, threading
os.environ['G6_SSE_HTTP']='1'
from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.unified_loop import UnifiedLoop
pub=SSEPublisher(diff=True)
loop=UnifiedLoop([pub],panels_dir='data/panels',refresh=0.1)
threading.Thread(target=lambda: loop.run(cycles=25),daemon=True).start()
print('Waiting before connect...')
time.sleep(0.5)
print('Events pre-connect', len(pub.events))
conn=http.client.HTTPConnection('127.0.0.1',9320,timeout=2)
conn.request('GET','/summary/events')
resp=conn.getresponse()
print('Status', resp.status)
print('Attempt incremental read lines:')
resp.fp.raw._sock.settimeout(0.5)
collected=b''
try:
    for i in range(10):
        chunk=resp.fp.readline()
        if not chunk:
            break
        collected+=chunk
        print('LINE', i, chunk)
        if b'event: hello' in collected and b'event: full_snapshot' in collected:
            break
except Exception as e:
    print('line read error', e)
print('Collected bytes', len(collected))
print(collected.decode('utf-8','ignore'))
conn.close()
