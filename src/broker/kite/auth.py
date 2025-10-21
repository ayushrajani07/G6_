"""Authentication & auth error classification helpers (Phase 5 + A7 split).

Extended to add small wrappers for client ensure + credential update so the
facade (`kite_provider.py`) can slim down further without re-implementing
bootstrap logic. These wrappers delegate to `client_bootstrap` but provide a
stable, auth-scoped import path for future enhancements (token refresh, expiry
proactive checks, etc.).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_AUTH_KEYWORDS = (
    "token expired",
    "invalid token",
    "unauthorized",
    "authentication failed",
    "permission denied",
)

def is_auth_error(exc: BaseException) -> bool:
    try:
        msg = str(exc).lower()
    except Exception:  # pragma: no cover
        return False
    return any(k in msg for k in _AUTH_KEYWORDS)

class AuthState:
    """Simple holder for future refresh metadata (refresh counts, last refresh ts)."""
    __slots__ = ("refresh_attempts", "last_error")
    def __init__(self) -> None:
        self.refresh_attempts = 0
        self.last_error: str | None = None

    def record_error(self, exc: BaseException) -> None:
        self.last_error = str(exc)


# ----------------------------------------------------------------------------
# Facade-slimming wrappers (A7 incremental extraction)
# ----------------------------------------------------------------------------
__all__ = [
    "is_auth_error",
    "AuthState",
    "ensure_client_auth",
    "update_credentials_auth",
]


def ensure_client_auth(provider) -> None:  # pragma: no cover - thin delegate
    try:
        from .client_bootstrap import ensure_client as _ensure
        _ensure(provider)
    except Exception:
        pass


def update_credentials_auth(provider, api_key: str | None = None, access_token: str | None = None, rebuild: bool = True) -> None:
    try:
        from .client_bootstrap import update_credentials as _update
        _update(provider, api_key=api_key, access_token=access_token, rebuild=rebuild)
    except Exception:
        # Minimal fallback preserving semantics
        if api_key:
            provider._api_key = api_key
        if access_token:
            provider._access_token = access_token
        if rebuild:
            provider._auth_failed = False
            provider.kite = None
            ensure_client_auth(provider)
        else:
            if getattr(provider, '_rl_fallback', lambda: False)():
                logger.info("Credentials updated (deferred rebuild; fallback path)")
