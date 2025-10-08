import warnings
import datetime
import os
import pytest
from src.broker.kite_provider import KiteProvider

pytestmark = pytest.mark.skipif(
    not bool(os.getenv('G6_ENABLE_BROKER_TESTS')),
    reason='Broker tests skipped (set G6_ENABLE_BROKER_TESTS=1 to enable)'
)


def test_provider_diagnostics_snapshot(monkeypatch):
    # Force synthetic fallback paths (no real credentials)
    monkeypatch.delenv('KITE_API_KEY', raising=False)
    monkeypatch.delenv('KITE_ACCESS_TOKEN', raising=False)
    # Instantiate provider (will emit DeprecationWarning by design)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always')
        kp = KiteProvider(api_key='dummy', access_token='dummy')
        # Expect at least one deprecation warning on init
        assert any(isinstance(x.message, DeprecationWarning) for x in w)
    diag = kp.provider_diagnostics()
    # Required keys present
    for key in ['option_cache_size','option_cache_hits','option_cache_misses','instruments_cached','expiry_dates_cached','synthetic_quotes_used','last_quotes_synthetic','used_instrument_fallback','token_age_sec','token_time_to_expiry_sec']:
        assert key in diag
    assert isinstance(diag['option_cache_size'], int)
    assert isinstance(diag['instruments_cached'], dict)


def test_provider_diagnostics_deprecated_property_shims(monkeypatch):
    monkeypatch.delenv('KITE_API_KEY', raising=False)
    monkeypatch.delenv('KITE_ACCESS_TOKEN', raising=False)
    # Suppress constructor deprecation globally here; individual property accesses still assert warning behavior
    with warnings.catch_warnings(record=True):
        warnings.simplefilter('ignore', DeprecationWarning)
        kp = KiteProvider(api_key='dummy', access_token='dummy')
    # Access deprecated properties and ensure warnings triggered only once each
    props = ['option_cache_hits','option_cache_misses','instruments_cache','expiry_dates_cache','synthetic_quotes_used','last_quotes_synthetic_flag']
    for p in props:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            getattr(kp, p)
            # exactly one deprecation warning for first access
            assert any(isinstance(x.message, DeprecationWarning) for x in w)
        # Second access should not duplicate warning
        with warnings.catch_warnings(record=True) as w2:
            warnings.simplefilter('always')
            getattr(kp, p)
            assert not any(isinstance(x.message, DeprecationWarning) for x in w2)
