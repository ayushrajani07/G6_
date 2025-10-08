"""Tests for structured logging events (A19)."""
from __future__ import annotations
import logging
from src.provider.auth import AuthManager
from src.provider.instruments import InstrumentCache
from src.provider.expiries import ExpiryResolver
from src.provider.metrics_adapter import set_metrics_sink, RecordingMetrics


def test_auth_logging_event(caplog, monkeypatch):
    caplog.set_level(logging.INFO)
    # Stub kiteconnect
    import builtins
    real_import = builtins.__import__
    def fake_import(name, *a, **k):
        if name == 'kiteconnect':
            class KC:
                def __init__(self, api_key):
                    pass
                def set_access_token(self, token):
                    pass
            return type('mod', (), {'KiteConnect': KC})
        return real_import(name, *a, **k)
    monkeypatch.setattr(builtins, '__import__', fake_import)
    am = AuthManager(api_key='k', access_token='t')
    am.ensure_client()
    assert any(r.message.startswith('provider.auth.init') for r in caplog.records)


def test_instrument_logging_events(caplog):
    caplog.set_level(logging.INFO)
    rec = RecordingMetrics(); set_metrics_sink(rec)
    cache = InstrumentCache()
    data = [{"symbol": "S"}]
    def fetch():
        return data
    out, fc = cache.get_or_fetch('NFO', fetch, ttl=60.0, now_func=lambda: 0.0)
    out2, fc2 = cache.get_or_fetch('NFO', fetch, ttl=60.0, now_func=lambda: 10.0)
    assert any('provider.instruments.fetch' in r.message for r in caplog.records)
    assert any('provider.instruments.cache' in r.message for r in caplog.records)


def test_expiries_fabricated_event(caplog):
    caplog.set_level(logging.INFO)
    res = ExpiryResolver()
    def fetch_instruments():
        # no instruments -> fabricate does not trigger (needs instruments without extracted expiries)
        return [{'segment': 'NFO-OPT', 'tradingsymbol': 'NIFTYX', 'strike': 100}]  # missing expiry -> triggers fabrication
    def atm_provider(_: str):
        return 100
    out = res.resolve('NIFTY', fetch_instruments, atm_provider, ttl=10.0, now_func=lambda: 0.0)
    assert len(out) == 2
    assert any('provider.expiries.fabricated' in r.message for r in caplog.records)
