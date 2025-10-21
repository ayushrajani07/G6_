"""Centralized provider configuration snapshot.

Reads environment variables once (aliases supported) and exposes
normalized, read-only properties for provider components.

Goals:
- Single source for credential discovery (avoid scattered os.environ lookups)
- Alias normalization (KITE_API_KEY vs KITE_APIKEY, etc.)
- Simple immutable snapshot semantics with explicit refresh/update
- Narrow public surface to ease future migration to file/secret store.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, replace

logger = logging.getLogger(__name__)

_PRIMARY_API_KEY_VARS = ("KITE_API_KEY", "KITE_APIKEY")
_PRIMARY_ACCESS_TOKEN_VARS = ("KITE_ACCESS_TOKEN", "KITE_ACCESSTOKEN")

@dataclass(frozen=True)
class ProviderConfig:
    api_key: str | None
    access_token: str | None
    discovered: bool  # whether values came from env (vs explicit update)

    def is_complete(self) -> bool:
        return bool(self.api_key and self.access_token)

    def with_updates(self, *, api_key: str | None = None, access_token: str | None = None) -> ProviderConfig:
        """Return a new config with updated credentials (explicit override)."""
        new_api = api_key if api_key is not None else self.api_key
        new_tok = access_token if access_token is not None else self.access_token
        return replace(self, api_key=new_api, access_token=new_tok, discovered=False)

_singleton_lock = threading.RLock()
_singleton: ProviderConfig | None = None


def _discover_from_env() -> ProviderConfig:
    api_key = None
    access_token = None
    for key in _PRIMARY_API_KEY_VARS:
        v = os.environ.get(key)
        if v:
            api_key = v
            break
    for key in _PRIMARY_ACCESS_TOKEN_VARS:
        v = os.environ.get(key)
        if v:
            access_token = v
            break
    cfg = ProviderConfig(api_key=api_key, access_token=access_token, discovered=True)
    if not cfg.is_complete():
        logger.debug("provider_config.incomplete api_key=%s access_token=%s", bool(api_key), bool(access_token))
    return cfg


def get_provider_config(refresh: bool = False) -> ProviderConfig:
    global _singleton
    with _singleton_lock:
        if _singleton is None or refresh:
            _singleton = _discover_from_env()
        return _singleton


def update_provider_credentials(api_key: str | None = None, access_token: str | None = None) -> ProviderConfig:
    """Explicitly override credentials (e.g., after refresh) returning new snapshot."""
    global _singleton
    with _singleton_lock:
        base = _singleton or _discover_from_env()
        _singleton = base.with_updates(api_key=api_key, access_token=access_token)
        return _singleton

__all__ = [
    "ProviderConfig",
    "get_provider_config",
    "update_provider_credentials",
]
