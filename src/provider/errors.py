"""Provider-specific error taxonomy bridging to pipeline phase taxonomy.

These errors mirror the semantics of the existing Phase* errors used in the
collection pipeline so downstream unified handling / metrics can classify
provider failures consistently without brittle string inspection.

Classification Hints:
 - ProviderRecoverableError: transient conditions (network hiccup, rate limit)
 - ProviderAuthError: credentials / token problems (may trigger refresh path)
 - ProviderFatalError: logic/data invariant broken (code bug or contract change)
 - ProviderTimeoutError: explicit timeout boundary (could be treated recoverable)

Mapping logic can be extended later to integrate with a unified metrics
counter (e.g., provider_error_total{kind="auth"}). For now we keep it
lightweight so we can refactor broad except blocks incrementally.
"""
from __future__ import annotations


class ProviderError(Exception):
    """Base provider error (do not raise directly)."""

class ProviderRecoverableError(ProviderError):
    """Transient / retryable error."""

class ProviderAuthError(ProviderRecoverableError):
    """Authentication / authorization credentials issue."""

class ProviderTimeoutError(ProviderRecoverableError):
    """Operation exceeded configured timeout bound."""

class ProviderFatalError(ProviderError):
    """Non-recoverable internal bug or data contract violation."""

_AUTH_TOKENS = ("auth", "token", "unauthorized", "forbidden", "expired")
_TIMEOUT_TOKENS = ("timeout", "timed out", "deadline")
_TRANSIENT_TOKENS = ("temporarily", "rate limit", "throttle", "connection reset", "connection aborted")

def classify_provider_exception(exc: BaseException) -> type[ProviderError]:
    """Best-effort classification of a raw exception instance.

    Heuristic order:
      1. Explicit subclass already part of taxonomy -> return its type
      2. Timeout hints -> ProviderTimeoutError
      3. Auth hints -> ProviderAuthError
      4. Transient hints -> ProviderRecoverableError
      5. Fallback -> ProviderFatalError
    """
    if isinstance(exc, ProviderError):  # already typed
        return type(exc)
    msg = str(exc).lower()
    if any(t in msg for t in _TIMEOUT_TOKENS):
        return ProviderTimeoutError
    if any(t in msg for t in _AUTH_TOKENS):
        return ProviderAuthError
    if any(t in msg for t in _TRANSIENT_TOKENS):
        return ProviderRecoverableError
    return ProviderFatalError

__all__ = [
    "ProviderError",
    "ProviderRecoverableError",
    "ProviderAuthError",
    "ProviderTimeoutError",
    "ProviderFatalError",
    "classify_provider_exception",
]
