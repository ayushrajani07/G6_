from __future__ import annotations

import os
from typing import Any, Dict

from .adapters.async_kite_adapter import AsyncKiteAdapter
from .adapters.async_mock_adapter import AsyncMockProvider


def create_async_provider(provider_type: str, config: Dict[str, Any] | None = None):
    ptype = (provider_type or "").lower()
    cfg = config or {}
    # Global defaults with env overrides
    max_workers = int(os.environ.get('G6_PARALLEL_MAX_WORKERS', cfg.get('max_workers', 8)))
    cps = float(os.environ.get('G6_KITE_RATE_LIMIT_CPS', cfg.get('rate_cps', 0)))
    burst = int(os.environ.get('G6_KITE_RATE_LIMIT_BURST', cfg.get('rate_burst', 0)))

    if ptype in ("kite", "zerodha", "kiteconnect"):
        from src.broker.kite_provider import KiteProvider
        api_key = cfg.get("api_key")
        access_token = cfg.get("access_token")
        prov = KiteProvider(api_key=api_key, access_token=access_token) if api_key and access_token else KiteProvider.from_env()
        return AsyncKiteAdapter(prov, max_workers=max_workers, cps=cps, burst=burst)
    if ptype in ("dummy", "mock"):
        return AsyncMockProvider()
    raise ValueError(f"Unsupported async provider type: {provider_type}")


__all__ = ["create_async_provider"]
