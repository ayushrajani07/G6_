"""Deprecated shim removed in A24.

Import path `src.providers.kite_provider` is no longer supported.
Use `from src.broker.kite_provider import KiteProvider` (and related symbols).

Rationale: centralization of provider code under broker namespace; shim kept
for multiple releases and now hard-removed to prevent silent divergence.
"""
raise ImportError(
    "Deprecated import path: use 'src.broker.kite_provider'. The providers.kite_provider shim was removed in A24."
)
