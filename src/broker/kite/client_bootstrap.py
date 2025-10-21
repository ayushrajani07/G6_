"""Client bootstrap & credential management (Phase A7 Step 4 extraction).

Encapsulates logic previously embedded in `KiteProvider` constructor / methods:
  * Environment hydration from .env
  * Initial client build when api_key & access_token present
  * Lazy ensure client (`_ensure_client` semantics)
  * Credential update with optional rebuild

The helpers mutate the provider instance in-place to preserve existing state
and public behavior. Logging tokens and throttling calls remain identical.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class _ProviderBootstrapLike(Protocol):
    """Minimal provider surface used by bootstrap helpers.

    We only access a few attributes and a fallback logging helper. All other
    interactions remain via getattr/guarded imports to avoid tight coupling.
    """

    kite: Any | None
    _api_key: str | None
    _access_token: str | None
    _auth_failed: bool

    def _rl_fallback(self) -> bool:
        ...


def hydrate_env(dotenv_path: str = '.env') -> None:
    """Best-effort .env hydration (KEY=VALUE lines)."""
    try:
        if os.path.exists(dotenv_path):
            with open(dotenv_path, encoding='utf-8') as _f:
                for _line in _f:
                    _line = _line.strip()
                    if not _line or _line.startswith('#') or '=' not in _line:
                        continue
                    k, v = _line.split('=', 1)
                    k = k.strip(); v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception:  # pragma: no cover
        pass


def build_client_if_possible(provider: _ProviderBootstrapLike) -> None:
    """Attempt immediate client construction if credentials present."""
    if provider.kite is not None:
        return
    api_key = getattr(provider, '_api_key', None)
    access_token = getattr(provider, '_access_token', None)
    if not (api_key and access_token):
        logger.info("KiteProvider constructed without credentials; will operate in no-client mode until provided.")
        return
    try:  # pragma: no cover (external import path)
        from kiteconnect import KiteConnect  # type: ignore
        kc = KiteConnect(api_key=api_key)
        kc.set_access_token(access_token)
        provider.kite = kc
        logger.info("Kite client initialized (constructor)")
    except Exception as e:  # pragma: no cover
        logger.warning(f"Kite client initial construction failed; will retry lazily: {e}")


def ensure_client(provider: _ProviderBootstrapLike) -> None:
    """Lazy construction mirroring original _ensure_client logic."""
    if provider.kite is not None or getattr(provider, '_auth_failed', False):
        return
    # Re-read credentials from environment if missing
    if not (provider._api_key and provider._access_token):
        # Attempt centralized config refresh
        try:
            from src.provider.config import get_provider_config as _get_pc  # type: ignore
            _pc = _get_pc(refresh=True)
            if _pc.is_complete():
                provider._api_key = _pc.api_key
                provider._access_token = _pc.access_token
                if provider._rl_fallback():
                    logger.info("Discovered credentials from provider config (late); attempting client init.")
            else:
                return
        except Exception:
            return
    try:  # pragma: no cover
        from kiteconnect import KiteConnect  # type: ignore
        kc = KiteConnect(api_key=provider._api_key)
        kc.set_access_token(provider._access_token)
        provider.kite = kc
        logger.info("Kite client initialized (lazy ensure_client)")
    except Exception as e:  # pragma: no cover
        if provider._rl_fallback():
            logger.warning(f"lazy_client_init_failed: {e}")


def update_credentials(
    provider: _ProviderBootstrapLike,
    api_key: str | None = None,
    access_token: str | None = None,
    rebuild: bool = True,
) -> None:
    if api_key:
        provider._api_key = api_key
    if access_token:
        provider._access_token = access_token
    if rebuild:
        provider._auth_failed = False
        provider.kite = None
        ensure_client(provider)
    else:
        if provider._rl_fallback():
            logger.info("Credentials updated (deferred rebuild)")


__all__ = [
    'hydrate_env',
    'build_client_if_possible',
    'ensure_client',
    'update_credentials',
]
