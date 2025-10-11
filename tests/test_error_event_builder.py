import time
from types import SimpleNamespace

# We will instantiate MetricsCache indirectly by crafting a lightweight stub mimicking required fields
from src.web.dashboard.metrics_cache import MetricsCache, ParsedMetrics

def _make_cache():
    # Provide dummy endpoint; we will not call start()/snapshot() so no network access occurs.
    # Use small interval (1) so cutoff window = 60s.
    return MetricsCache(endpoint="http://localhost:0", interval=1)

def test_error_events_empty_history():
    mc = _make_cache()
    pm = ParsedMetrics(ts=time.time())
    evs = mc._build_error_events(pm, max_events=10)
    assert evs == []

def test_error_events_single_delta():
    mc = _make_cache()
    now = time.time()
    # Inject a single errors snapshot into history
    mc._history.append((now - 10, {'kind': 'errors', 'errors': {'NIFTY|fetch_fail': 3}}))
    pm = ParsedMetrics(ts=now)
    evs = mc._build_error_events(pm, max_events=10)
    assert len(evs) == 1
    e = evs[0]
    assert e['index'] == 'NIFTY'
    assert e['error_type'] == 'fetch_fail'
    assert e['delta'] == 3  # previous value defaults 0
    assert e['ago'] >= 0


def test_error_events_multiple_capped_and_negative_filtered():
    mc = _make_cache()
    base = time.time()
    # Previous older snapshot with some counts
    mc._history.append((base - 50, {'kind': 'errors', 'errors': {
        'NIFTY|fetch_fail': 2,
        'BANKNIFTY|timeout': 5,
    }}))
    # Newer snapshot increments some, repeats others, adds one zero-delta and one decreased (should filter)
    mc._history.append((base - 10, {'kind': 'errors', 'errors': {
        'NIFTY|fetch_fail': 5,     # delta +3
        'BANKNIFTY|timeout': 4,    # delta -1 (filtered)
        'FINNIFTY|parse': 0,       # delta 0 (filtered)
        'SENSEX|new_error': 7      # delta +7 (no previous -> delta 7)
    }}))
    pm = ParsedMetrics(ts=base)
    evs = mc._build_error_events(pm, max_events=3)  # cap at 3
    # Expect only positive deltas up to cap. A decreased value in a newer snapshot may still surface as an earlier positive delta from an older snapshot inside window.
    assert len(evs) <= 3
    assert all(ev['delta'] > 0 for ev in evs)


def test_error_events_ordering_newest_first():
    mc = _make_cache()
    now = time.time()
    mc._history.append((now - 70, {'kind': 'errors', 'errors': {'NIFTY|a': 1}}))
    mc._history.append((now - 40, {'kind': 'errors', 'errors': {'NIFTY|a': 2, 'NIFTY|b': 1}}))
    mc._history.append((now - 10, {'kind': 'errors', 'errors': {'NIFTY|a': 5, 'NIFTY|b': 4}}))
    pm = ParsedMetrics(ts=now)
    evs = mc._build_error_events(pm, max_events=10)
    # Should include latest positive deltas only (a: +3 from 2->5, b: +3 from 1->4)
    # Both have ts = now-10 (newest), ordering stable
    assert len(evs) >= 2
    assert all(ev['ts'] == (now - 10) for ev in evs[:2])
    # Ensure older snapshot delta for 'a' not duplicated
    a_events = [ev for ev in evs if ev['error_type'] == 'a']
    assert len(a_events) == 1
