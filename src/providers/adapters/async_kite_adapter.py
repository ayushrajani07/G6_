from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..rate_limiter import RateLimiterRegistry


class AsyncKiteAdapter:
    """Async wrapper around the sync KiteProvider using a thread pool.

    Applies a token-bucket rate limiter (per-process) to avoid bursts.
    """

    def __init__(self, provider, *, max_workers: int | None = None, cps: float = 0.0, burst: int = 0):
        self._prov = provider
        self._loop = asyncio.get_event_loop()
        self._pool = ThreadPoolExecutor(max_workers=max_workers) if max_workers else None
        self._rl = RateLimiterRegistry().get("kite", cps, burst)

    async def close(self) -> None:  # pragma: no cover - simple
        # No async resources; shut down pool if owned
        if self._pool:
            self._pool.shutdown(wait=False, cancel_futures=True)
        try:
            if hasattr(self._prov, 'close'):
                await self._loop.run_in_executor(self._pool, self._prov.close)
        except Exception:
            pass

    async def _call(self, fn, *args, **kwargs):
        await self._rl.acquire(1)
        return await self._loop.run_in_executor(self._pool, lambda: fn(*args, **kwargs))

    async def get_quote(self, instruments: list[tuple[str, str]]) -> dict[str, Any]:
        return await self._call(self._prov.get_quote, instruments)

    async def get_ltp(self, instruments: list[tuple[str, str]]) -> dict[str, Any]:
        return await self._call(self._prov.get_ltp, instruments)

    async def resolve_expiry(self, index_symbol: str, expiry_rule: str):
        return await self._call(self._prov.resolve_expiry, index_symbol, expiry_rule)

    async def option_instruments(self, index_symbol: str, expiry_date, strikes: list[int]):
        return await self._call(self._prov.option_instruments, index_symbol, expiry_date, strikes)

    async def get_option_instruments(self, index_symbol: str, expiry_date, strikes: list[int]):
        # Prefer get_option_instruments; fall back to option_instruments
        if hasattr(self._prov, 'get_option_instruments'):
            return await self._call(self._prov.get_option_instruments, index_symbol, expiry_date, strikes)
        return await self._call(self._prov.option_instruments, index_symbol, expiry_date, strikes)


__all__ = ["AsyncKiteAdapter"]
