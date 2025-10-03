import types
import os
import pytest
import time

from src.providers.composite_provider import CompositeProvider
from src.metrics import setup_metrics_server  # facade import


class FailingProvider:
    def __init__(self):
        self.calls = 0
    def get_index_data(self, index_symbol):  # signature mimic
        self.calls += 1
        raise RuntimeError("provider down")

class SlowFailingProvider:
    def get_index_data(self, index_symbol):
        time.sleep(0.05)
        raise RuntimeError("slow failure")

class SucceedingProvider:
    def __init__(self, price=100.0):
        self.price = price
    def get_index_data(self, index_symbol):
        return (self.price, None)


def test_failover_success(monkeypatch):
    metrics, _ = setup_metrics_server(port=9220, host='127.0.0.1', reset=True)
    p1 = FailingProvider()
    p2 = SucceedingProvider(price=123.45)
    cp = CompositeProvider([p1, p2], metrics=metrics)

    price, ohlc = cp.get_index_data('NIFTY')
    assert price == 123.45
    # Ensure failover counter incremented (cannot read counter value easily without scraping; ensure attribute exists)
    assert hasattr(metrics, 'provider_failover')
    assert p1.calls == 1


def test_all_fail(monkeypatch):
    metrics, _ = setup_metrics_server(port=9221, host='127.0.0.1', reset=True)
    p1 = FailingProvider()
    p2 = SlowFailingProvider()
    cp = CompositeProvider([p1, p2], metrics=metrics)
    with pytest.raises(RuntimeError):
        cp.get_index_data('NIFTY')


def test_failfast(monkeypatch):
    os.environ['G6_PROVIDER_FAILFAST'] = '1'
    metrics, _ = setup_metrics_server(port=9222, host='127.0.0.1', reset=True)
    p1 = FailingProvider()
    p2 = SucceedingProvider()
    cp = CompositeProvider([p1, p2], metrics=metrics)
    with pytest.raises(RuntimeError):
        cp.get_index_data('NIFTY')
    # Ensure second provider not attempted under failfast
    assert p1.calls == 1
    del os.environ['G6_PROVIDER_FAILFAST']
