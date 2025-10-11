from __future__ import annotations
import os, json, time, socket
import pytest

pytestmark = []  # parallel-safe when using tmp_path and dynamic ports

def test_panels_transaction_commit_cleans_staging(tmp_path):
    base = tmp_path / 'panels'
    os.environ['G6_OUTPUT_SINKS'] = 'panels'
    os.environ['G6_PANELS_DIR'] = str(base)
    from src.utils.output import get_output
    r = get_output(reset=True)
    with r.begin_panels_txn() as txn:
        r.panel_update('alpha', {'v': 1})
    # committed file present
    assert (base / 'alpha.json').exists()
    # staging root either absent or empty
    txn_root = base / '.txn'
    if txn_root.exists():
        # allow brief window for async filesystem lag on Windows
        deadline = time.time() + 0.5
        while time.time() < deadline and any(txn_root.iterdir()):
            time.sleep(0.02)
        assert not any(txn_root.iterdir()), 'staging directory not cleaned after commit'


def test_summary_diff_counter_seed_after_reset(monkeypatch):
    # Force diff mode
    monkeypatch.setenv('G6_SUMMARY_RICH_DIFF','1')
    from scripts.summary.plugins.base import SummarySnapshot, TerminalRenderer
    from scripts.summary import summary_metrics as sm
    # Simulate external reset after baseline seeding
    h1 = {'a':'1','b':'2'}; h2 = {'a':'1','b':'3'}
    snap1 = SummarySnapshot(status={'indices': ['X'], 'alerts': []}, derived={}, panels={}, ts_read=0, ts_built=0, cycle=1, errors=(), panel_hashes=h1)
    snap2 = SummarySnapshot(status={'indices': ['X'], 'alerts': []}, derived={}, panels={}, ts_read=0, ts_built=0, cycle=2, errors=(), panel_hashes=h2)
    tr = TerminalRenderer(rich_enabled=False)
    tr.process(snap1)
    sm._reset_in_memory()  # type: ignore
    tr.process(snap2)
    m = sm.snapshot()
    # label for b (changed) should exist
    assert any(lbls and any(l[1]=='b' for l in lbls) for (_n,lbls),_v in m['counter'].items()), 'expected counter label for panel b'


@pytest.fixture()
def sse_port(monkeypatch) -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    monkeypatch.setenv('G6_SSE_HTTP_PORT', str(port))
    return port


def test_sse_ip_window_cleared(monkeypatch, sse_port: int):
    # First test artificially populate window then ensure fixture reset clears before second connection test logic
    monkeypatch.setenv('G6_SSE_HTTP','1')
    monkeypatch.setenv('G6_SSE_IP_CONNECT_RATE','1/60')  # only one allowed
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.unified_loop import UnifiedLoop
    pub = SSEPublisher(diff=True)
    loop = UnifiedLoop([pub], panels_dir='data/panels', refresh=0.05)
    import threading, time as _t, http.client
    t = threading.Thread(target=lambda: loop.run(cycles=10), daemon=True)
    t.start()
    # Readiness for SSE port
    deadline = _t.time() + 2.0
    while _t.time() < deadline:
        s = socket.socket(); s.settimeout(0.05)
        try:
            s.connect(("127.0.0.1", sse_port))
            s.close()
            break
        except Exception:
            try: s.close()
            except Exception: pass
            _t.sleep(0.025)
    # First connection (allowed)
    headers={'User-Agent':'TestClient/1'}
    c1 = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    c1.request('GET','/summary/events', headers=headers)
    r1 = c1.getresponse(); assert r1.status == 200
    c1.close()
    # Manually import window and assert it has one entry
    from scripts.summary import sse_http as sseh
    assert sseh._ip_conn_window, 'expected populated window'
    # Simulate new test start by invoking autouse fixture logic manually
    if hasattr(sseh, '_ip_conn_window'):
        sseh._ip_conn_window.clear()
    # Second connection should succeed again after manual reset
    c2 = http.client.HTTPConnection('127.0.0.1', sse_port, timeout=2)
    c2.request('GET','/summary/events', headers=headers)
    r2 = c2.getresponse(); assert r2.status == 200
    c2.close()
