"""Shared typing helpers for gating layer.

Isolated to avoid circular imports while letting both orchestrator and
metrics gating reference common structural contracts.

This module deliberately keeps Protocols permissive (minimal attribute
surface) so that legacy dynamic objects can satisfy them without
modification. Future waves can refine as stability increases.
"""
from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable


class ProviderLike(Protocol):  # minimal surface used in readiness probe
    def get_ltp(self, symbol: str) -> Any: ...  # returns price-like (int/float/str)

class ProviderProbeResult(TypedDict):
    ok: bool
    reason: str

@runtime_checkable
class MetricsRegistryLike(Protocol):  # subset used in metrics.gating
    _metric_groups: dict[str, str]  # mapping attr -> group name
    def __getattr__(self, name: str) -> Any: ...  # allow dynamic metric attributes
    def __setattr__(self, name: str, value: Any) -> None: ...

class MarketHoursAPI(Protocol):  # optional injection candidate (not yet used)
    def is_market_open(self, **kwargs: Any) -> bool: ...
    def get_next_market_open(self) -> Any: ...
    def sleep_until_market_open(self, **kwargs: Any) -> None: ...

GatingDecision = str  # placeholder alias; could become Literal['run','skip_market_closed','skip_interval'] later

__all__ = [
    'ProviderLike',
    'ProviderProbeResult',
    'MetricsRegistryLike',
    'MarketHoursAPI',
    'GatingDecision',
]
