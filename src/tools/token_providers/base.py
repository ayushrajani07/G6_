from __future__ import annotations

from typing import Protocol


class TokenProvider(Protocol):  # pragma: no cover - interface
    """Protocol for token acquisition providers."""

    name: str

    def validate(self, api_key: str, access_token: str) -> bool:  # noqa: D401
        """Return True if token appears valid (may perform network call)."""
        raise NotImplementedError

    def acquire(
        self,
        api_key: str,
        api_secret: str,
        headless: bool = False,
        interactive: bool = True,
    ) -> str | None:  # noqa: D401
        """Attempt to obtain a new token. Return token or None."""
        raise NotImplementedError
