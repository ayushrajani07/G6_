"""Async provider protocol for parallel collection path.

This mirrors the sync Provider surface but uses async methods suitable for
asyncio orchestration. Adapters will wrap sync providers like KiteProvider.
"""
from __future__ import annotations

from typing import Protocol, Dict, List, Tuple, Any
from datetime import date


class AsyncProvider(Protocol):
    async def close(self) -> None:  # pragma: no cover - trivial
        ...

    # Quotes / Prices
    async def get_quote(self, instruments: List[Tuple[str, str]]) -> Dict[str, Any]:
        ...

    async def get_ltp(self, instruments: List[Tuple[str, str]]) -> Dict[str, Any]:
        ...

    # Options discovery
    async def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> date:
        ...

    async def option_instruments(self, index_symbol: str, expiry_date: Any, strikes: List[int]) -> List[Dict[str, Any]]:
        ...

    async def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: List[int]) -> List[Dict[str, Any]]:
        ...


__all__ = ["AsyncProvider"]
