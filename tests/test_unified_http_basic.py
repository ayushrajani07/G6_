from __future__ import annotations
import os, time, http.client, json

def test_unified_http_endpoints(monkeypatch):
    monkeypatch.setenv('G6_UNIFIED_HTTP','1')
    monkeypatch.setenv('G6_SSE_HTTP','0')  # ensure legacy not used
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop

    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.1)

    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=4), daemon=True)
    t.start()
    time.sleep(0.5)

    # Health check
    hc = http.client.HTTPConnection('127.0.0.1', 9329, timeout=3)
    hc.request('GET', '/summary/health')
    r = hc.getresponse()
    assert r.status == 200
    body = json.loads(r.read().decode('utf-8'))
    assert body.get('ok') is True and 'schema_version' in body
    hc.close()

    # Resync endpoint
    rc = http.client.HTTPConnection('127.0.0.1', 9329, timeout=3)
    rc.request('GET', '/summary/resync')
    rr = rc.getresponse()
    assert rr.status == 200
    resync_body = json.loads(rr.read().decode('utf-8'))
    assert 'panels' in resync_body and 'schema_version' in resync_body
    rc.close()

    # SSE events
    sc = http.client.HTTPConnection('127.0.0.1', 9329, timeout=3)
    sc.request('GET', '/summary/events')
    sr = sc.getresponse()
    assert sr.status == 200
    # Incremental SSE read (line-based) to avoid depending on large buffered read
    lines=[]; end=time.time()+2.5
    while time.time()<end:
        line=sr.fp.readline()
        if not line: break
        lines.append(line.decode('utf-8','ignore'))
        joined=''.join(lines)
        if 'event: hello' in joined or 'event: full_snapshot' in joined:
            break
    joined=''.join(lines)
    assert 'event: full_snapshot' in joined or 'event: hello' in joined
    sc.close()
