import os, json
from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import PanelsWriter
from scripts.summary.unified_loop import UnifiedLoop as UL
from scripts.summary.plugins.base import TerminalRenderer
from scripts.summary.plugins.base import MetricsEmitter
from scripts.summary.snapshot_builder import build_frame_snapshot

class DummySnap:
    def __init__(self, cycle: int, status: dict):
        self.cycle = cycle
        self.status = status
        self.domain = None
        self.panel_hashes = None
        self.derived = {}
        self.panels = {}
        self.errors = tuple()
        self.ts_built = 0.0


def test_sse_publisher_heartbeat(monkeypatch):
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES','2')
    pub = SSEPublisher(diff=True)
    # Build status with minimal panels base
    status = {'indices_detail': {}, 'alerts': []}
    # First process -> hello + full_snapshot
    pub.process(DummySnap(1, status))
    evts1 = [e['event'] for e in pub.events]
    assert evts1 == ['hello','full_snapshot']
    # Two unchanged cycles -> heartbeat should appear after second
    pub.process(DummySnap(2, status))
    pub.process(DummySnap(3, status))
    evts2 = [e['event'] for e in pub.events]
    assert 'heartbeat' in evts2, f"heartbeat missing events={evts2}"


def test_sse_publisher_panel_update_and_metrics(monkeypatch):
    monkeypatch.setenv('G6_SSE_HEARTBEAT_CYCLES','5')
    pub = SSEPublisher(diff=True)
    # Hashing uses keys: header, indices, analytics, alerts, links, perfstore, storage
    base_status = {'alerts': []}
    pub.process(DummySnap(1, base_status))
    # Change hashed content: add an alert so 'alerts' hash changes
    changed_status = {'alerts': [{'level':'INFO','msg':'hi'}]}
    pub.process(DummySnap(2, changed_status))
    events = pub.events
    assert any(e['event'] in ('panel_update','panel_diff') for e in events if e['event'] not in ('hello','full_snapshot'))
    ms = pub.metrics_snapshot()
    assert ms['panel_updates'] == 1
