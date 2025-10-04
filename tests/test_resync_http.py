from __future__ import annotations
import json, os, time, threading, http.client

from scripts.summary.http_resync import serve_resync, set_last_snapshot
from scripts.summary.schema import SCHEMA_VERSION
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import OutputPlugin, SummarySnapshot

class _StubPlugin(OutputPlugin):
    name = 'stub'
    def process(self, snap):
        return

def _build_fake_snapshot(cycle:int=1):
    # Minimal duck-typed SummarySnapshot creation via UnifiedLoop builder would require loop plumbing;
    # so construct a simple object with expected attributes used by handler.
    class _Snap:
        def __init__(self):
            self.status = { 'panel_push_meta': {}, 'indices': [1,2,3] }
            self.cycle = cycle
            self.domain = None
            self.panel_hashes = { 'indices': 'deadbeef' }
        errors = ()
    return _Snap()


def test_resync_http_basic_parity(monkeypatch):
    # Start server on ephemeral port
    srv = serve_resync(port=0, background=True)
    addr = srv.server_address
    # server_address may be (host, port) for IPv4 or (host, port, *_rest) for IPv6
    host = addr[0]
    port = addr[1]
    snap = _build_fake_snapshot()
    set_last_snapshot(snap)
    # Give server a moment
    time.sleep(0.05)
    conn = http.client.HTTPConnection(str(host), port, timeout=2)
    conn.request('GET', '/summary/resync')
    resp = conn.getresponse()
    body = resp.read().decode('utf-8')
    data = json.loads(body)
    assert resp.status == 200
    assert data['schema_version'] == SCHEMA_VERSION
    assert 'panels' in data and 'indices' in data['panels']
    assert data['panels']['indices']['hash'] == 'deadbeef'
    assert data['cycle'] == 1
    conn.close()
