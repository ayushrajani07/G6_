from src.bus.in_memory_bus import get_bus

def test_publish_and_poll_order():
    bus = get_bus('t1')
    ids = [bus.publish('evt', {'i': i}) for i in range(5)]
    # Subscribe with from_id=0 to request backlog (prototype semantics: clamp to head if older)
    sub = bus.subscribe(from_id=0)
    events = sub.poll()
    assert [e.id for e in events] == ids


def test_overflow_drops():
    bus = get_bus('overflow')
    bus.max_retained = 3
    for i in range(6):
        bus.publish('x', {'i': i})
    # Head id should have advanced (6 events, capacity 3 => dropped 3)
    assert bus.head_id() == 3
    sub = bus.subscribe(from_id=0)
    evs = sub.poll()
    assert len(evs) == 3
    assert [e.id for e in evs] == [3,4,5]


def test_subscriber_lag_updates():
    bus = get_bus('lag')
    sub = bus.subscribe()
    for i in range(10):
        bus.publish('a', {'i': i})
    # Poll smaller batch to create lag
    part = sub.poll(batch_size=5)
    assert len(part) == 5
    rest = sub.poll()
    assert len(rest) == 5
