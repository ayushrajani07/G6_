from __future__ import annotations
import http.client, time, threading, json, os, socket
import pytest

from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.unified_loop import UnifiedLoop

# Integration test strategy:
# 1. Enable SSE + HTTP + short heartbeat interval.
# 2. Run unified loop for multiple cycles.
# 3. Modify underlying status between cycles by mutating publisher snapshot status.
# 4. Capture stream bytes and assert presence of hello, full_snapshot, panel_update, heartbeat.


def _run_loop_with_mutation(publisher: SSEPublisher, cycles: int = 8):
    loop = UnifiedLoop([publisher], panels_dir='data/panels', refresh=0.05)
    # Background thread to mutate indices panel after a couple cycles to trigger diff
    def mutator():
        # Sleep enough for initial hello + full_snapshot
        time.sleep(0.25)
        # Inject synthetic change: modify status indices list through publisher events baseline
        # We can't directly change snapshot mid-loop, so we rely on domain/status changes via publisher hash
        # Simplest path: monkeypatch publisher internal last_hashes to force diff next cycle
        try:
            publisher._last_hashes = {k: 'force_diff' + v for k, v in (publisher._last_hashes or {}).items()}  # type: ignore[attr-defined]
        except Exception:
            pass
    threading.Thread(target=mutator, daemon=True).start()
    loop.run(cycles=cycles)


@pytest.fixture()
def sse_port(monkeypatch) -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(port))
    return port


def test_sse_stream_integration(monkeypatch, sse_port: int):
    monkeypatch.setenv('G6_SSE_HTTP','1')
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES','2')  # faster heartbeat
    pub = SSEPublisher(diff=True)
    t = threading.Thread(target=lambda: _run_loop_with_mutation(pub, cycles=10), daemon=True)
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
    conn = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=4)
    conn.request('GET','/summary/events')
    resp = conn.getresponse()
    assert resp.status == 200
    raw = b''
    # Read bursts for up to ~2.5s
    end = time.time() + 2.5
    while time.time() < end and (b'event: heartbeat' not in raw or b'event: panel_update' not in raw):
        chunk = resp.read(1024)
        if not chunk:
            break
        raw += chunk
    text = raw.decode('utf-8','ignore')
    # Assertions: essential event types
    assert 'event: hello' in text
    assert 'event: full_snapshot' in text
    # We expect at least one panel_update due to forced hash mutation
    assert 'event: panel_update' in text
    # Heartbeat should appear because of idle cycles threshold
    assert 'event: heartbeat' in text
    conn.close()
