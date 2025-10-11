from __future__ import annotations
import os, time, http.client, json, socket
import pytest

# This test exercises the minimal SSE HTTP endpoint by starting a unified loop with
# SSE enabled and verifying that at least hello + full_snapshot events arrive.


@pytest.fixture()
def sse_port(monkeypatch) -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(port))
    return port


def test_sse_http_stream_minimal(monkeypatch, sse_port: int):
    # Enable SSE HTTP endpoint (publisher now always active when instantiated)
    monkeypatch.setenv('G6_SSE_HTTP', '1')
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES', '2')

    # Build a very small loop with just SSE publisher
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop

    publisher = SSEPublisher(diff=True)
    loop = UnifiedLoop([publisher], panels_dir='data/panels', refresh=0.1)

    # Run a few cycles in a background thread
    import threading
    # Run more cycles to ensure server still active when client connects
    t = threading.Thread(target=lambda: loop.run(cycles=25), daemon=True)
    t.start()
    # Readiness probe for SSE port to avoid race
    deadline = time.time() + 2.0
    while time.time() < deadline:
        s = socket.socket(); s.settimeout(0.05)
        try:
            s.connect(("127.0.0.1", sse_port))
            s.close()
            break
        except Exception:
            try: s.close()
            except Exception: pass
            time.sleep(0.025)

    # Connect to SSE endpoint
    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    conn.request('GET', '/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    # Incremental read to avoid blocking on large fixed-size buffering
    buf = []
    deadline = time.time() + 2.0
    while time.time() < deadline:
        line = resp.fp.readline()
        if not line:
            break
        try:
            buf.append(line.decode('utf-8','ignore'))
        except Exception:
            buf.append(str(line))
        joined = ''.join(buf)
        if 'event: hello' in joined and 'event: full_snapshot' in joined:
            break
    raw = ''.join(buf)
    assert 'event: hello' in raw
    assert 'event: full_snapshot' in raw
    conn.close()
