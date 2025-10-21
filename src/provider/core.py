"""Core aggregation object for modular provider (Phase 4 A7 skeleton).

Holds references to subcomponents. For the initial patch each subcomponent
is a lightweight placeholder exposing the methods that the legacy provider
will eventually delegate to.
"""
from __future__ import annotations

from dataclasses import dataclass

from .auth import AuthManager
from .diagnostics import Diagnostics
from .expiries import ExpiryResolver
from .instruments import InstrumentCache


@dataclass
class ProviderCore:
    auth: AuthManager
    instruments: InstrumentCache
    expiries: ExpiryResolver
    diagnostics: Diagnostics

    @classmethod
    def build(cls) -> ProviderCore:
        return cls(
            auth=AuthManager(),
            instruments=InstrumentCache(),
            expiries=ExpiryResolver(),
            diagnostics=Diagnostics(),
        )
