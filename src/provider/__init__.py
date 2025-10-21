"""Provider skeleton package (Phase 4 A7).

Initial modularization scaffold. This package will gradually absorb logic
from the legacy provider facade (`src.broker.kite_provider`). For the first
patch we only declare structural placeholders; no functional changes.

Export the facade for early adoption; legacy code can switch imports later:
    from src.provider import get_instruments

Revision Date: 2025-10-07
"""
from .facade import (
    _debug_legacy_provider_id,
    get_expiry_dates,
    get_instruments,
    get_monthly_expiries,
    get_weekly_expiries,
    provider_diagnostics,
    resolve_expiry,
)  # noqa: F401

__all__ = [
    "get_instruments",
    "get_expiry_dates",
    "get_weekly_expiries",
    "get_monthly_expiries",
    "resolve_expiry",
    "provider_diagnostics",
    "_debug_legacy_provider_id",
]
