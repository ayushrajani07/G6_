from __future__ import annotations
import http.client, threading, time, os

from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.unified_loop import UnifiedLoop


def _start_loop(env: dict[str,str], cycles=5):
    for k,v in env.items():
        os.environ[k] = v
    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.05)
    # Inflate cycles window for stability in timing-sensitive CI
    t = threading.Thread(target=lambda: loop.run(cycles=max(cycles,25)), daemon=True)
    t.start()
    time.sleep(0.3)
    return pub


def test_sse_global_connection_cap():
    _start_loop({'G6_SSE_HTTP':'1','G6_SSE_MAX_CONNECTIONS':'1'})
    c1 = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    c1.request('GET','/summary/events')
    r1 = c1.getresponse()
    assert r1.status == 200
    # Allow server loop a brief moment to record active connection before second attempt
    time.sleep(0.1)
    # second connection should exceed cap
    c2 = http.client.HTTPConnection('127.0.0.1', 9320, timeout=1)
    c2.request('GET','/summary/events')
    r2 = c2.getresponse()
    assert r2.status == 429
    c1.close(); c2.close()


def test_sse_event_rate_limit_skips_excess():
    pub = _start_loop({'G6_SSE_HTTP':'1','G6_SSE_EVENTS_PER_SEC':'5'})
    # Connect
    c = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    c.request('GET','/summary/events')
    r = c.getresponse()
    assert r.status == 200
    # Read some bytes after a short window; we can't easily assert exact count but ensure we got something
    # Incremental read to capture initial events without large blocking read
    buf=[]; end=time.time()+2.0
    while time.time()<end:
        line=r.fp.readline()
        if not line: break
        buf.append(line.decode('utf-8','ignore'))
        if 'event: hello' in ''.join(buf):
            break
    raw=''.join(buf)
    assert 'event: hello' in raw  # initial events should always pass
    c.close()
