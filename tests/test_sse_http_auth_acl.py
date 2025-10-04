from __future__ import annotations
import http.client, time


def _start_loop(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP', '1')
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop
    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.05)
    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=25), daemon=True)
    t.start()
    time.sleep(0.3)


def test_sse_rejects_bad_token(monkeypatch):
    monkeypatch.setenv('G6_SSE_API_TOKEN', 'secret')
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    conn.request('GET', '/summary/events')  # no token header
    resp = conn.getresponse()
    assert resp.status == 401
    conn.close()


def test_sse_accepts_good_token(monkeypatch):
    monkeypatch.setenv('G6_SSE_API_TOKEN', 'secret2')
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    conn.putrequest('GET', '/summary/events')
    conn.putheader('X-API-Token', 'secret2')
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 200
    conn.close()


def test_sse_ip_allowlist_blocks(monkeypatch):
    monkeypatch.setenv('G6_SSE_IP_ALLOW', '10.0.0.1,10.0.0.2')  # not including localhost
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 403
    conn.close()


def test_sse_ip_allowlist_allows_localhost(monkeypatch):
    monkeypatch.setenv('G6_SSE_IP_ALLOW', '127.0.0.1,10.0.0.2')
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', 9320, timeout=2)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    conn.close()
