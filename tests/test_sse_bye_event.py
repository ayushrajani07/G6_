from __future__ import annotations
import time, http.client, socket
import pytest

# Test that a graceful shutdown emits a bye event on the SSE stream (legacy separate SSE server path).

@pytest.fixture()
def sse_port(monkeypatch) -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(port))
    return port


def test_sse_bye_event_on_shutdown(monkeypatch, sse_port: int):
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
    # Readiness wait for server
    deadline = time.time() + 2.0
    while time.time() < deadline:
        s = socket.socket(); s.settimeout(0.05)
        try:
            s.connect(("127.0.0.1", sse_port))
            s.close(); break
        except Exception:
            try: s.close()
            except Exception: pass
            time.sleep(0.025)

    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=3)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    # Trigger shutdown after we start reading
    initiate_sse_shutdown('test')
    # Allow some time for bye to flush
    data = resp.read(8192).decode('utf-8', errors='ignore')
    assert 'event: bye' in data
    conn.close()
