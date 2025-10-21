"""Centralized mutable state for KiteProvider (Phase 4).

This module isolates caches and counters so the main provider class can focus on
external API logic. It also makes it easier to test cache invalidation and
introspection in isolation.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProviderState:
    # Instruments (raw) cache per exchange + fetch timestamp metadata
    instruments_cache: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    instruments_cache_meta: dict[str, float] = field(default_factory=dict)

    # Expiry date list per index
    expiry_dates_cache: dict[str, list[datetime.date]] = field(default_factory=dict)

    # Option instruments cache (key tuple -> instrument dict)
    option_instrument_cache: dict[tuple, dict[str, Any]] = field(default_factory=dict)
    option_cache_day: str = field(default_factory=lambda: datetime.date.today().isoformat())
    option_cache_hits: int = 0
    option_cache_misses: int = 0

    # Daily universe + loaded date
    daily_universe: list[dict[str, Any]] | None = None
    daily_universe_loaded_date: str | None = None

    # Synthetic / fallback diagnostics
    synthetic_quotes_used: int = 0
    last_quotes_synthetic: bool = False
    used_fallback: bool = False
    auth_failed: bool = False

    def reset_option_cache_if_new_day(self) -> None:
        today = datetime.date.today().isoformat()
        if self.option_cache_day != today:
            self.option_instrument_cache.clear()
            self.option_cache_day = today
            # Do not reset counters so we can observe long-run hit/miss ratios

    def record_option_cache_hit(self) -> None:
        self.option_cache_hits += 1

    def record_option_cache_miss(self) -> None:
        self.option_cache_misses += 1

    def invalidate_instruments(self, exchange: str | None = None) -> None:
        if exchange:
            self.instruments_cache.pop(exchange, None)
            self.instruments_cache_meta.pop(exchange, None)
        else:
            self.instruments_cache.clear()
            self.instruments_cache_meta.clear()

    def invalidate_expiries(self, index_symbol: str | None = None) -> None:
        if index_symbol:
            self.expiry_dates_cache.pop(index_symbol, None)
        else:
            self.expiry_dates_cache.clear()

    def reset_synthetic_counters(self) -> None:
        self.synthetic_quotes_used = 0
        self.last_quotes_synthetic = False

    def summary(self) -> dict[str, Any]:  # lightweight diagnostic snapshot
        return {
            'option_cache_size': len(self.option_instrument_cache),
            'option_cache_hits': self.option_cache_hits,
            'option_cache_misses': self.option_cache_misses,
            'instruments_cache_exchanges': list(self.instruments_cache.keys()),
            'expiry_keys': list(self.expiry_dates_cache.keys())[:10],
            'synthetic_quotes_used': self.synthetic_quotes_used,
            'last_quotes_synthetic': self.last_quotes_synthetic,
            'used_fallback': self.used_fallback,
            'auth_failed': self.auth_failed,
        }
