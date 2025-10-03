from __future__ import annotations

from src.events.event_bus import EventBus

def test_panel_generation_increments_and_embeds():
    bus = EventBus(max_events=16)
    full1 = bus.publish('panel_full', {'status': {'v': 1}}, coalesce_key='panel_full')
    assert full1.payload.get('_generation') == 1
    diff1 = bus.publish('panel_diff', {'diff': {'added': {'k': 2}}})
    assert diff1.payload.get('_generation') == 1
    full2 = bus.publish('panel_full', {'status': {'v': 2}}, coalesce_key='panel_full')
    assert full2.payload.get('_generation') == 2
    diff2 = bus.publish('panel_diff', {'diff': {'added': {'k': 3}}})
    assert diff2.payload.get('_generation') == 2
    events = bus.get_since(0)
    gens_all = [e.payload.get('_generation') for e in events if e.event_type in ('panel_full','panel_diff')]
    gens = [g for g in gens_all if isinstance(g, int)]
    # Expect monotonic non-decreasing and at least one 1 then 2
    assert 1 in gens and 2 in gens
    assert gens == sorted(gens)
