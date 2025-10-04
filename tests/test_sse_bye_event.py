from __future__ import annotations
import time, http.client

# Test that a graceful shutdown emits a bye event on the SSE stream (legacy separate SSE server path).

def test_sse_bye_event_on_shutdown(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP','1')
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES','1')
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop
    from scripts.summary.sse_http import initiate_sse_shutdown

    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.1)

    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=5), daemon=True)
    t.start()
    time.sleep(0.4)

    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=3)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    # Trigger shutdown after we start reading
    initiate_sse_shutdown('test')
    # Allow some time for bye to flush
    data = resp.read(8192).decode('utf-8', errors='ignore')
    assert 'event: bye' in data
    conn.close()
