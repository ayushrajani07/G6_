import datetime as dt
from src.collectors.helpers.expiry_map import build_expiry_map


def test_build_expiry_map_basic():
    today = dt.date.today()
    insts = [
        {'instrument_token': 1, 'expiry': today, 'strike': 100, 'foo': 'a'},
        {'instrument_token': 2, 'expiry': today, 'strike': 110},
        {'instrument_token': 3, 'expiry_date': today, 'strike': 120},  # alternate key
    ]
    mapping, stats = build_expiry_map(insts)
    assert len(mapping) == 1
    assert today in mapping
    assert stats['total'] == 3
    assert stats['invalid_expiry'] == 0
    assert stats['valid'] == 3
    assert len(mapping[today]) == 3


def test_build_expiry_map_invalid_and_mixed():
    today = dt.date.today()
    bad = dt.datetime.now()  # local-ok  # datetime (should normalize)
    insts = [
        {'instrument_token': 1, 'expiry': today},
        {'instrument_token': 2, 'exp': bad},  # datetime path
        {'instrument_token': 3, 'expiry': '2025-13-01'},  # invalid month
        {'instrument_token': 4, 'expiry': 'not-a-date'},
        {'instrument_token': 5},  # missing
    ]
    mapping, stats = build_expiry_map(insts)
    assert len(mapping) == 1
    assert today in mapping
    # total instruments processed
    assert stats['total'] == len(insts)
    # two invalid strings + missing + invalid iso month => 3 (invalid month counts) +1 missing +1 not-a-date = 3? Actually:
    # invalid month -> invalid, not-a-date -> invalid, missing -> invalid. Valid are first two (expiry date + datetime)
    assert stats['valid'] == 2
    assert stats['invalid_expiry'] == stats['total'] - stats['valid']


def test_build_expiry_map_empty():
    mapping, stats = build_expiry_map([])
    assert mapping == {}
    assert stats['total'] == 0
    assert stats['unique_expiries'] == 0
    assert stats['avg_per_expiry'] == 0.0
