"""Archived SSE diagnostic script.

Captured original logic to:
  - Launch UnifiedLoop with SSEPublisher
  - Connect via raw HTTP client and print early event lines

Modern approach: rely on structured SSE tests under scripts/summary tests.
"""
import http.client, time, os, threading  # noqa: F401
from scripts.summary.plugins.sse import SSEPublisher  # noqa: F401
from scripts.summary.unified_loop import UnifiedLoop  # noqa: F401

def _run_demo():  # pragma: no cover
    os.environ['G6_SSE_HTTP'] = '1'
    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.1)
    threading.Thread(target=lambda: loop.run(cycles=25), daemon=True).start()
    print('Waiting before connect...')
    time.sleep(0.5)
    print('Events pre-connect', len(pub.events))
    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    print('Status', resp.status)
    collected = b''
    try:
        for _ in range(10):
            chunk = resp.fp.readline()
            if not chunk:
                break
            collected += chunk
            if b'event: hello' in collected and b'event: full_snapshot' in collected:
                break
    except Exception as e:  # pragma: no cover
        print('line read error', e)
    print(collected.decode('utf-8', 'ignore'))
    conn.close()

if __name__ == '__main__':  # pragma: no cover
    print('Archived SSE diagnostic script; use tests for validation.')
    _run_demo()
