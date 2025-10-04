"""Test domain snapshot reuse path in SSE subset builder.

Currently we simulate presence of a domain snapshot by calling internal subset
builder twice and ensuring no exception; we cannot directly inject domain via
public API yet, so this test guards future regression by verifying subset build
with rebuild fallback is stable.
"""
from __future__ import annotations

from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.plugins.base import SummarySnapshot
from scripts.summary.domain import build_domain_snapshot


def make_snap(cycle, status, domain=None):
    return SummarySnapshot(status=status, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=cycle, errors=(), model=None, domain=domain, panel_hashes=None)


def test_subset_builder_stability(monkeypatch):
    pub = SSEPublisher(diff=True)
    status0 = {"indices": ["X"], "alerts": {"total": 0}, "resources": {"cpu_pct": 1.0, "memory_mb": 11.0}, "app": {"version": "1"}}
    domain0 = build_domain_snapshot(status0)
    pub.process(make_snap(0, status0, domain=domain0))
    # Change resources panel
    status1 = {"indices": ["X"], "alerts": {"total": 0}, "resources": {"cpu_pct": 2.0, "memory_mb": 12.0}, "app": {"version": "1"}}
    domain1 = build_domain_snapshot(status1)
    pub.process(make_snap(1, status1, domain=domain1))
    # Assert no internal domain rebuilds occurred (reuse path hit)
    assert pub.domain_rebuilds == 0
    # Ensure last event references only resources or appropriate diff type
    last = pub.events[-1]
    if last['event'] == 'panel_update':
        keys = {u['key'] for u in last['data']['updates']}
        assert 'resources' in keys
    elif last['event'] == 'panel_diff':
        assert 'resources' in last['data']['panels']
    else:
        raise AssertionError('Unexpected event in domain reuse test')
