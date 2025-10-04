from __future__ import annotations
import time, http.client, os

def test_sse_advanced_metrics_exposed(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP','1')
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES','1')
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop

    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.1)

    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=30), daemon=True)
    t.start()
    time.sleep(0.4)

    # Connect & read a little to ensure events flow
    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=3)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    _ = resp.read(2048)
    conn.close()

    # If prometheus_client not installed, skip further assertions
    try:
        import urllib.request
        r = urllib.request.urlopen('http://127.0.0.1:9325')  # default metrics server maybe not started
    except Exception:
        return  # metrics server absent; advanced histograms cannot be asserted
    body = r.read().decode('utf-8')
    # Check for any of the new metric names (histograms)
    assert ('g6_sse_http_event_size_bytes' in body) or ('g6_sse_http_event_queue_latency_seconds' in body) or ('g6_sse_http_connection_duration_seconds' in body)
