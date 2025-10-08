from __future__ import annotations
import os
import time

from src.streaming import get_stream_bus, StreamEvent


def test_inmem_publish_and_subscribe_basic(monkeypatch):
    monkeypatch.setenv('G6_STREAM_BACKEND', 'INMEM')
    bus = get_stream_bus('test')
    sub = bus.subscribe()
    # publish a few events
    for i in range(3):
        res = bus.publish('tick', {'i': i})
        assert res.event_id == i
        assert res.elapsed_ms >= 0
    polled = sub.poll()
    assert len(polled) == 3
    assert [e.payload['i'] for e in polled] == [0,1,2]


def test_schema_hash_emission_idempotent(monkeypatch):
    monkeypatch.setenv('G6_STREAM_BACKEND', 'INMEM')
    bus = get_stream_bus('schema')
    sub = bus.subscribe()
    for i in range(2):
        bus.publish('evt', {'a': 1, 'b': {'nested': True}})
    polled = sub.poll()
    assert len(polled) == 2
    # Ensure second publish still returns expected id sequence
    assert polled[0].id == 0
    assert polled[1].id == 1


def test_backend_stub_reject_subscribe(monkeypatch):
    monkeypatch.setenv('G6_STREAM_BACKEND', 'REDIS')
    bus = get_stream_bus('stub')
    try:
        bus.subscribe()
        assert False, 'Expected NotImplementedError'
    except NotImplementedError:
        pass

