"""Tests for provider skeleton facade (Phase 4 A7 Patch 1).

These tests intentionally avoid asserting on real provider behaviour; they
only ensure the new import surface exists and returns structurally valid
objects so downstream refactors have a safety net.
"""
from __future__ import annotations
import os

# Ensure skeleton flag does not disable anything accidentally
os.environ.setdefault("G6_PROVIDER_SKELETON", "1")

def test_facade_imports():
    from src.provider import get_instruments, get_expiry_dates, get_weekly_expiries, get_monthly_expiries, resolve_expiry, provider_diagnostics  # noqa: E501
    assert callable(get_instruments)
    assert callable(get_expiry_dates)
    assert callable(get_weekly_expiries)
    assert callable(get_monthly_expiries)
    assert callable(resolve_expiry)
    assert callable(provider_diagnostics)


def test_facade_instruments_empty_list_shape():
    from src.provider import get_instruments
    out = get_instruments(exchange="NFO", force_refresh=True)
    assert isinstance(out, list)


def test_facade_expiries_list_shape():
    from src.provider import get_expiry_dates, get_weekly_expiries, get_monthly_expiries
    exp_all = get_expiry_dates("NIFTY")
    assert isinstance(exp_all, list)
    weekly = get_weekly_expiries("NIFTY")
    assert isinstance(weekly, list)
    monthly = get_monthly_expiries("NIFTY")
    assert isinstance(monthly, list)


def test_facade_resolve_expiry_rule_safe():
    from src.provider import resolve_expiry
    d = resolve_expiry("NIFTY", "current-week")
    # Date or fallback object
    assert hasattr(d, 'year')


def test_facade_provider_diagnostics_shape():
    from src.provider import provider_diagnostics
    snap = provider_diagnostics()
    assert isinstance(snap, dict)


def test_facade_legacy_singleton_identity():
    from src.provider import _debug_legacy_provider_id, get_instruments, get_expiry_dates  # type: ignore
    first_id = _debug_legacy_provider_id()
    # Trigger some calls to ensure lazy init executed
    get_instruments(exchange="NFO", force_refresh=False)
    get_expiry_dates("NIFTY")
    second_id = _debug_legacy_provider_id()
    assert second_id is not None
    if first_id is not None:
        # If already initialized earlier in test run, id should be stable
        assert first_id == second_id
