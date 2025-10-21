#!/usr/bin/env python3
"""
Typed provider interface for the G6 platform.

This defines the minimal surface that the Providers facade relies on. Concrete
implementations may offer more methods; adapters can normalize them as needed.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Protocol


class Provider(Protocol):
    """Minimal provider protocol used by the Providers facade and collectors."""

    def close(self) -> None:
        ...

    # Quotes / Prices
    def get_quote(self, instruments: list[tuple[str, str]]) -> dict[str, Any]:
        """Return quotes keyed by "EXCHANGE:SYMBOL" with at least last_price/ohlc when available."""
        ...

    def get_ltp(self, instruments: list[tuple[str, str]]) -> dict[str, Any]:
        """Return last traded price mapping keyed by "EXCHANGE:SYMBOL" with last_price field."""
        ...

    # Options discovery
    def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> date:
        ...

    def option_instruments(self, index_symbol: str, expiry_date: Any, strikes: list[int]) -> list[dict[str, Any]]:
        ...

    def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: list[int]) -> list[dict[str, Any]]:
        ...


__all__ = ["Provider"]
