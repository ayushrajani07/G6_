"""Tests for provider metrics adapter instrumentation (A18)."""
from __future__ import annotations
from src.provider.metrics_adapter import RecordingMetrics, set_metrics_sink, metrics
from src.provider.auth import AuthManager
from src.provider.instruments import InstrumentCache


def test_auth_manager_metrics_on_init_success(monkeypatch):
    rec = RecordingMetrics()
    set_metrics_sink(rec)

    class FakeKite:
        def set_access_token(self, *_):
            pass
    # Patch kiteconnect import inside AuthManager.ensure_client
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *args, **kwargs):
        if name == 'kiteconnect':
            class KC:  # minimal stub
                def __init__(self, api_key):
                    self.api_key = api_key
                def set_access_token(self, token):
                    self.token = token
            return type('mod', (), { 'KiteConnect': KC })
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', fake_import)

    am = AuthManager(api_key='k', access_token='t')
    am.ensure_client()
    assert any(c[0] == 'provider_auth_init_total' and c[1]['status'] == 'ok' for c in rec.counters)


def test_instrument_cache_metrics(monkeypatch):
    rec = RecordingMetrics()
    set_metrics_sink(rec)
    cache = InstrumentCache()
    data = [{"symbol": "A"}]
    def fetch():
        return data
    out, from_cache = cache.get_or_fetch('NFO', fetch, ttl=60.0, now_func=lambda: 0.0)
    assert not from_cache
    out2, from_cache2 = cache.get_or_fetch('NFO', fetch, ttl=60.0, now_func=lambda: 10.0)
    assert from_cache2
    # Expect one ok fetch and one cache hit metric
    fetch_outcomes = [c for c in rec.counters if c[0] == 'provider_instruments_fetch_total']
    assert any(c[1]['outcome'] == 'ok' for c in fetch_outcomes)
    cache_hits = [c for c in rec.counters if c[0] == 'provider_instruments_cache_total']
    assert any(c[1]['outcome'] == 'hit' for c in cache_hits)
    observations = [o for o in rec.observations if o[0] == 'provider_instruments_fetch_seconds']
    assert observations, 'Expected timing observation for fetch'
