from __future__ import annotations
import http.client, time, socket
import pytest


@pytest.fixture()
def sse_port(monkeypatch) -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(port))
    return port


def _start_loop(monkeypatch):
    monkeypatch.setenv('G6_SSE_HTTP', '1')
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop
    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.05)
    import threading
    t = threading.Thread(target=lambda: loop.run(cycles=25), daemon=True)
    t.start()
    # Readiness wait on configured port
    try:
        port = int(monkeypatch.getenv('G6_SSE_HTTP_PORT') or '0')  # type: ignore[attr-defined]
    except Exception:
        port = 0
    if not port:
        try:
            import os
            port = int(os.getenv('G6_SSE_HTTP_PORT') or '0')
        except Exception:
            port = 0
    if port:
        deadline = time.time() + 2.0
        while time.time() < deadline:
            s = socket.socket(); s.settimeout(0.05)
            try:
                s.connect(("127.0.0.1", port))
                s.close(); break
            except Exception:
                try: s.close()
                except Exception: pass
                time.sleep(0.025)
    else:
        time.sleep(0.3)


def test_sse_rejects_bad_token(monkeypatch, sse_port: int):
    monkeypatch.setenv('G6_SSE_API_TOKEN', 'secret')
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(sse_port))
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    conn.request('GET', '/summary/events')  # no token header
    resp = conn.getresponse()
    assert resp.status == 401
    conn.close()


def test_sse_accepts_good_token(monkeypatch, sse_port: int):
    monkeypatch.setenv('G6_SSE_API_TOKEN', 'secret2')
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(sse_port))
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    conn.putrequest('GET', '/summary/events')
    conn.putheader('X-API-Token', 'secret2')
    conn.endheaders()
    resp = conn.getresponse()
    assert resp.status == 200
    conn.close()


def test_sse_ip_allowlist_blocks(monkeypatch, sse_port: int):
    monkeypatch.setenv('G6_SSE_IP_ALLOW', '10.0.0.1,10.0.0.2')  # not including localhost
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(sse_port))
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 403
    conn.close()


def test_sse_ip_allowlist_allows_localhost(monkeypatch, sse_port: int):
    monkeypatch.setenv('G6_SSE_IP_ALLOW', '127.0.0.1,10.0.0.2')
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(sse_port))
    _start_loop(monkeypatch)
    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    conn.close()
