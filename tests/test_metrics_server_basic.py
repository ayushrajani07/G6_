from __future__ import annotations
import os, time, http.client

def test_metrics_server_exposes_sse_metrics(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP','1')
    monkeypatch.setenv('G6_SUMMARY_METRICS_HTTP','1')
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop
    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.05)
    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=2), daemon=True)
    t.start()
    time.sleep(0.4)
    # scrape metrics
    conn = http.client.HTTPConnection('127.0.0.1', 9325, timeout=2)
    conn.request('GET','/metrics')
    resp = conn.getresponse()
    body = resp.read().decode('utf-8','ignore')
    assert resp.status == 200
    # Presence of at least one SSE metric name (may be zero events but family registered)
    assert 'g6_sse_http_active_connections' in body or 'g6_sse_http_connections_total' in body
    conn.close()
