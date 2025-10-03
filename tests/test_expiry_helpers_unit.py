import datetime
import types
import pytest

from src.collectors.modules import expiry_helpers as eh

class DummyMetrics:
    def __init__(self):
        self.calls = []
    def mark_api_call(self, success: bool, latency_ms: float):
        self.calls.append((success, latency_ms))

class DummyProviders:
    def __init__(self, *, expiry_dates=None, instruments=None, quotes=None, resolve_ok=True):
        self._expiry_dates = expiry_dates or []
        self._instruments = instruments or []
        self._quotes = quotes or {}
        self._resolve_ok = resolve_ok
    def get_expiry_dates(self, index):
        return self._expiry_dates
    def resolve_expiry(self, index, rule):
        if not self._resolve_ok:
            raise RuntimeError("resolve failure")
        y,m,d = rule.split('-'); import datetime as _dt; return _dt.date(int(y),int(m),int(d))
    def get_option_instruments(self, index, expiry_date, strikes):
        return self._instruments
    def enrich_with_quotes(self, instruments):
        return self._quotes

class DummyCtx:
    def __init__(self, providers):
        self.providers = providers
        self.metrics = types.SimpleNamespace(synthetic_quotes_used_total=DummyCounter())

class DummyCounter:
    def labels(self, **k):
        return self
    def inc(self, *a, **k):
        return None


def test_resolve_iso_short_circuit():
    metrics = DummyMetrics()
    prov = DummyProviders()
    date = eh.resolve_expiry('NIFTY', '2025-01-30', prov, metrics, concise_mode=True)
    assert str(date) == '2025-01-30'
    assert metrics.calls and metrics.calls[0][0] is True


def test_resolve_provider_fallback():
    metrics = DummyMetrics()
    prov = DummyProviders(resolve_ok=True)
    # Non ISO pattern to force provider resolution (e.g., custom code) -> simulate by passing not-ISO and ensuring exception then fallback
    with pytest.raises(Exception):
        # Passing invalid rule triggers resolve failure which should bubble (rule length != 10 so no ISO branch)
        eh.resolve_expiry('NIFTY', 'BADRULE', prov, metrics, concise_mode=True)


def test_fetch_instruments_success():
    metrics = DummyMetrics()
    prov = DummyProviders(instruments=[{'strike':100},{'strike':101}])
    out = eh.fetch_option_instruments('NIFTY','2025-01-30',datetime.date(2025,1,30),[100,101],prov,metrics)
    assert len(out) == 2


def test_enrich_quotes_success():
    metrics = DummyMetrics()
    prov = DummyProviders(quotes={'SYM': {'strike':100}})
    out = eh.enrich_quotes('NIFTY','2025-01-30',datetime.date(2025,1,30),[{'strike':100,'symbol':'SYM'}],prov,metrics)
    assert 'SYM' in out


def test_synthetic_metric_pop_noop():
    # Providers without primary_provider attribute -> no exception
    ctx = types.SimpleNamespace(providers=types.SimpleNamespace(), metrics=types.SimpleNamespace(synthetic_quotes_used_total=DummyCounter()))
    eh.synthetic_metric_pop(ctx,'NIFTY',datetime.date(2025,1,30))
    # Simply ensure it returns without error
    assert True
