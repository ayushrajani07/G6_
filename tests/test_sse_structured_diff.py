from __future__ import annotations
import os, time

def test_sse_structured_diff_basic(monkeypatch):
    monkeypatch.setenv('G6_SSE_STRUCTURED','1')
    from scripts.summary.plugins.sse import SSEPublisher
    from scripts.summary.plugins.base import SummarySnapshot

    pub = SSEPublisher(diff=True)
    # Initial snapshot triggers hello + full_snapshot
    snap1 = SummarySnapshot(status={'indices':['NIFTY'], 'alerts':{'total':0}}, derived={}, panels={}, ts_read=time.time(), ts_built=time.time(), cycle=1, errors=())
    pub.process(snap1)
    events = pub.events
    assert any(e.get('event')=='hello' for e in events)
    assert any(e.get('event')=='full_snapshot' for e in events)
    # Second snapshot with a change -> should emit panel_diff (structured mode)
    snap2 = SummarySnapshot(status={'indices':['NIFTY','BANKNIFTY'], 'alerts':{'total':0}}, derived={}, panels={}, ts_read=time.time(), ts_built=time.time(), cycle=2, errors=())
    pub.process(snap2)
    events2 = pub.events
    assert any(e.get('event')=='panel_diff' for e in events2), f"Events: {[e.get('event') for e in events2]}"