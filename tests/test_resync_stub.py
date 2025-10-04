import os
from scripts.summary.resync import get_resync_snapshot
from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.plugins.base import SummarySnapshot
import time

def test_resync_snapshot_basic_parity(monkeypatch):
    # Enable SSE so publisher runs
    status = {
        'indices': ['NIFTY','BANKNIFTY'],
        'alerts': {'total': 2, 'severity_counts': {'warn':1,'info':1}},
        'resources': {'cpu_pct': 12.3, 'memory_mb': 456.7},
        'cycle': {'number': 5},
    }
    snap = SummarySnapshot(
        status=status,
        derived={},
        panels={},
        ts_read=time.time(),
        ts_built=time.time(),
        cycle=5,
        errors=(),
        model=None,
        domain=None,
        panel_hashes=None,
    )
    pub = SSEPublisher()
    pub.setup({})
    pub.process(snap)
    events = pub.events
    full = next(e for e in events if e['event'] == 'full_snapshot')
    fs = full['data']
    # Build resync snapshot reusing hashes
    hashes = {k: v['hash'] for k,v in fs['panels'].items()}
    rs = get_resync_snapshot(status, cycle=5, reuse_hashes=hashes)
    assert rs['cycle'] == fs['cycle']
    # Ensure at least the same panel keys
    assert set(rs['panels'].keys()) == set(fs['panels'].keys())
    # Hash parity
    for k in hashes:
        assert rs['panels'][k]['hash'] == hashes[k]
