"""Tests for Diagnostics expansion (A17)."""
from __future__ import annotations
from src.provider.diagnostics import Diagnostics
from src.provider.core import ProviderCore


def test_snapshot_basic_keys():
    core = ProviderCore.build()
    diag = Diagnostics()
    snap = diag.snapshot(core=core, legacy_provider=None)
    # Base key
    assert 'emitted_diagnostics' in snap
    # Auth key present
    assert 'auth_failed' in snap
    # Instrument cache detail present (empty)
    assert 'instrument_cache_detail' in snap
    assert snap['instrument_totals'] == 0


def test_snapshot_with_legacy_provider_flags():
    # Create a minimal stand-in object with expected attributes
    class LegacyStub:
        _synthetic_quotes_used = 5
        _last_quotes_synthetic = True
        _used_fallback = False
    legacy = LegacyStub()
    diag = Diagnostics()
    snap = diag.snapshot(core=None, legacy_provider=legacy)
    assert snap['legacy_synthetic_quotes_used'] == 5
    assert snap['legacy_last_quotes_synthetic'] is True
    assert snap['legacy_used_instrument_fallback'] is False
