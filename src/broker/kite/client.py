"""Kite client factory (Phase 5).

Isolates creation of the underlying KiteConnect-like client so the main provider
logic can focus on domain behavior. This module keeps imports lazy to avoid the
heavy dependency cost on cold paths (tests using dummy subclasses).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)

class KiteLike(Protocol):  # Minimal protocol subset used by provider
    def instruments(self, exchange: str) -> list[dict[str, Any]]: ...
    def ltp(self, instruments: list[tuple[str, str]]) -> dict[str, Any]: ...
    def quote(self, instruments: list[tuple[str, str]]) -> dict[str, Any]: ...

_DEF_TIMEOUT = 5.0

class ClientConfig:
    def __init__(self, api_key: str | None, access_token: str | None, timeout: float):
        self.api_key = api_key
        self.access_token = access_token
        self.timeout = timeout

    @classmethod
    def from_provider_config(cls) -> ClientConfig:
        try:
            from src.provider.config import get_provider_config as _get_pc  # type: ignore
            _pc = _get_pc()
            api_key = _pc.api_key
            token = _pc.access_token
        except Exception:
            api_key = None
            token = None
        try:
            timeout = float(os.environ.get("KITE_TIMEOUT_SEC", _DEF_TIMEOUT))
        except Exception:
            timeout = _DEF_TIMEOUT
        return cls(api_key, token, timeout)


def create_kite_client(cfg: ClientConfig) -> KiteLike | None:
    """Instantiate a Kite-like client.

    Returns None if credentials missing (provider will operate in degraded/dummy mode).
    Separated for easier mocking in tests.
    """
    if not cfg.api_key or not cfg.access_token:
        logger.debug("Kite client not created (missing creds)")
        return None
    try:
        from kiteconnect import KiteConnect  # type: ignore
    except Exception as e:  # pragma: no cover - dependency not always installed in minimal test env
        logger.warning("kiteconnect import failed: %s", e)
        return None
    try:
        kc = KiteConnect(api_key=cfg.api_key, timeout=cfg.timeout)
        kc.set_access_token(cfg.access_token)
        logger.debug("Kite client created (timeout=%s)", cfg.timeout)
        return kc  # type: ignore[return-value]
    except Exception:  # pragma: no cover - defensive
        logger.error("Failed to create Kite client", exc_info=True)
        return None
