"""Tests for InstrumentCache migration logic (A15)."""
from __future__ import annotations
from src.provider.instruments import InstrumentCache


def test_get_or_fetch_basic_cache_hit():
    cache = InstrumentCache()
    calls = {"fetch": 0}
    data = [{"symbol": "A"}]

    def fetch():
        calls["fetch"] += 1
        return data

    out1, from_cache1 = cache.get_or_fetch("NFO", fetch, ttl=60.0, now_func=lambda: 0.0)
    assert out1 == data and from_cache1 is False and calls["fetch"] == 1
    # second call within TTL
    out2, from_cache2 = cache.get_or_fetch("NFO", fetch, ttl=60.0, now_func=lambda: 10.0)
    assert out2 == data and from_cache2 is True and calls["fetch"] == 1


def test_get_or_fetch_empty_short_ttl_and_retry():
    cache = InstrumentCache()
    timeline = {"t": 0.0}

    def now_func():
        return timeline["t"]

    calls = {"fetch": 0}

    def fetch_empty():
        calls["fetch"] += 1
        return []

    def fetch_nonempty():
        calls["fetch"] += 1
        return [{"symbol": "B"}]

    # First call returns empty then retry returns non-empty
    out, from_cache = cache.get_or_fetch(
        "NFO",
        fetch_empty,
        ttl=100.0,
        short_empty_ttl=5.0,
        retry_on_empty=True,
        retry_fetch=fetch_nonempty,
        now_func=now_func,
    )
    assert out and not from_cache and calls["fetch"] == 2

    # Advance time beyond short_empty_ttl but within full TTL -> still cache hit (non-empty)
    timeline["t"] = 10.0
    out2, from_cache2 = cache.get_or_fetch(
        "NFO", fetch_empty, ttl=100.0, short_empty_ttl=5.0, now_func=now_func
    )
    assert out2 and from_cache2 is True


def test_get_or_fetch_force_refresh():
    cache = InstrumentCache()
    calls = {"fetch": 0}

    def fetch():
        calls["fetch"] += 1
        return [{"symbol": "C"}]

    out1, f1 = cache.get_or_fetch("NFO", fetch, ttl=50.0, now_func=lambda: 0.0)
    assert f1 is False and calls["fetch"] == 1
    out2, f2 = cache.get_or_fetch("NFO", fetch, ttl=50.0, force_refresh=True, now_func=lambda: 10.0)
    assert f2 is False and calls["fetch"] == 2 and out1 == out2


def test_get_or_fetch_unexpected_shape():
    cache = InstrumentCache()

    def fetch_bad():
        return {"wrong": 1}

    out, from_cache = cache.get_or_fetch("NFO", fetch_bad, ttl=10.0, now_func=lambda: 0.0)
    assert out == [] and from_cache is False
