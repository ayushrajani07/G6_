#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Provider factory for the G6 platform.

Creates concrete provider implementations based on simple type identifiers.
Backwards compatible: reuses existing broker.kite_provider classes.
"""
from __future__ import annotations

from typing import Any, Dict


def create_provider(provider_type: str, config: Dict[str, Any] | None = None):
    ptype = (provider_type or "").lower()
    cfg = config or {}
    if ptype in ("kite", "zerodha", "kiteconnect"):
        from src.broker.kite_provider import KiteProvider
        # Prefer env for credentials; config keys are optional passthroughs
        api_key = cfg.get("api_key")
        access_token = cfg.get("access_token")
        if api_key and access_token:
            return KiteProvider(api_key=api_key, access_token=access_token)
        return KiteProvider.from_env()
    if ptype in ("dummy", "mock"):
        from src.broker.kite_provider import DummyKiteProvider
        return DummyKiteProvider()
    raise ValueError(f"Unsupported provider type: {provider_type}")


__all__ = ["create_provider"]
