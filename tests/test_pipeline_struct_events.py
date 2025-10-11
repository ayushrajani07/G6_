from __future__ import annotations

def test_pipeline_struct_events_buffer_and_flag(monkeypatch):
    # Turn on structured events and buffer
    monkeypatch.setenv('G6_PIPELINE_STRUCT_EVENTS','1')
    monkeypatch.setenv('G6_PIPELINE_STRUCT_EVENTS_BUFFER','2')
    from src.collectors.pipeline.struct_events import emit_struct_event
    class State:
        def __init__(self):
            self.meta = {}
    s = State()
    emit_struct_event('expiry.phase.event', {'phase':'x','outcome':'ok','attempt':1}, state=s)
    emit_struct_event('expiry.phase.event', {'phase':'y','outcome':'ok','attempt':1}, state=s)
    emit_struct_event('expiry.phase.event', {'phase':'z','outcome':'ok','attempt':1}, state=s)
    buf = s.meta.get('struct_events')
    assert isinstance(buf, list)
    assert len(buf) == 2
    assert buf[0]['phase'] == 'y'
    assert buf[1]['phase'] == 'z'
