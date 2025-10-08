import os
import warnings
import pytest
from src.providers.factory import create_provider

BROKER_ENABLED = bool(os.getenv('G6_ENABLE_BROKER_TESTS'))


def test_create_dummy_provider():
    p = create_provider('dummy', {})
    # Should at least have a close() method per protocol
    assert hasattr(p, 'close')


@pytest.mark.skipif(not BROKER_ENABLED, reason='Broker tests skipped (set G6_ENABLE_BROKER_TESTS=1 to enable)')
def test_create_kite_provider_from_env(monkeypatch):
    # Provide fake credentials; provider init should not raise. Localize deprecation warning capture.
    monkeypatch.setenv('KITE_API_KEY', 'test_key')
    monkeypatch.setenv('KITE_ACCESS_TOKEN', 'test_token')
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        p = create_provider('kite', {})
        # Expect exactly one deprecation warning originating from KiteProvider construction
        dep_warnings = [x for x in w if isinstance(x.message, DeprecationWarning)]
        assert dep_warnings, "Expected KiteProvider deprecation warning not emitted"
    assert hasattr(p, 'close')
