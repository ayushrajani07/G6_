import time
import json

from src.events.event_bus import get_event_bus


def test_events_last_full_unixtime_gauge_and_publish_unixtime():
    bus = get_event_bus()
    # Force metrics registration (lazy) before publishing to ensure events_last_full_unixtime gauge created
    try:
        bus._maybe_register_metrics()  # type: ignore[attr-defined]
    except Exception:
        pass
    # Publish a full then a diff
    full = bus.publish('panel_full', {'status': {'x': 1}})
    diff = bus.publish('panel_diff', {'diff': {'changed': {'status': {'x': {'old': 1, 'new': 2}}}}})

    # Payloads should have publish_unixtime and _generation
    assert '_generation' in full.payload and isinstance(full.payload['_generation'], int)
    assert 'publish_unixtime' in full.payload and isinstance(full.payload['publish_unixtime'], float)
    assert 'publish_unixtime' in diff.payload and isinstance(diff.payload['publish_unixtime'], float)
    assert diff.payload['_generation'] == full.payload['_generation']  # same generation (no new full yet)

    # Gauge for events_last_full_unixtime should have been registered and set (access via metrics exposition)
    # We collect raw metrics text from prometheus_client registry (best-effort)
    from prometheus_client import REGISTRY
    metric_text = []
    for fam in REGISTRY.collect():
        if fam.name == 'g6_events_last_full_unixtime':
            # Should have at least one sample with a recent timestamp value
            samples = fam.samples
            assert samples, 'No samples for g6_events_last_full_unixtime'
            val = samples[0].value
            # Value should be within last 10 seconds
            assert (time.time() - val) < 10, f'events_last_full_unixtime too old: {val}'
            break
    else:
        raise AssertionError('g6_events_last_full_unixtime metric not found')


def test_publish_unixtime_monotonic_order():
    bus = get_event_bus()
    try:
        bus._maybe_register_metrics()  # type: ignore[attr-defined]
    except Exception:
        pass
    a = bus.publish('panel_diff', {'diff': {'changed': {}}})
    time.sleep(0.01)
    b = bus.publish('panel_diff', {'diff': {'changed': {}}})
    assert a.payload['publish_unixtime'] <= b.payload['publish_unixtime']
