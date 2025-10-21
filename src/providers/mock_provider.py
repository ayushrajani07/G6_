from __future__ import annotations

"""Synchronous shim MockProvider wrapping AsyncMockProvider for test fixtures.

Provides minimal synchronous methods expected by collectors or orchestrator tests
without requiring an event loop.
"""
import math
import time
from datetime import date, timedelta
from typing import Any


class MockProvider:
    def __init__(self):
        self._start = time.time()
        self._bases = {
            'NIFTY': 20000.0,
            'BANKNIFTY': 45000.0,
            'FINNIFTY': 21000.0,
            'SENSEX': 66000.0,
        }

    def _ltp_value(self, symbol: str) -> float:
        base = self._bases.get(symbol, 10000.0)
        t = time.time() - self._start
        amp = base * 0.0015
        return round(base + math.sin(t / 30.0) * amp, 2)

    # Simplified synchronous APIs -------------------------------------------------
    def get_index_data(self, index_symbol: str) -> dict[str, Any]:
        return { 'last_price': self._ltp_value(index_symbol) }

    def resolve_expiry(self, index_symbol: str, expiry_rule: str) -> date:  # pragma: no cover - trivial
        today = date.today()
        for i in range(1,8):
            d = today + timedelta(days=i)
            if d.weekday() == 3:  # Thursday
                return d
        return today + timedelta(days=7)

    # Optional placeholder to mirror async mock adapter interface (unused paths)
    def close(self):  # pragma: no cover
        return None

__all__ = ["MockProvider"]
