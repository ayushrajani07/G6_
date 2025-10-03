"""Authentication & auth error classification helpers (Phase 5)."""
from __future__ import annotations
from typing import Any

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
