from __future__ import annotations


class FakeTokenProvider:
    """Deterministic fake provider for tests & headless workflows.

    - validate: returns True iff access_token is non-empty
    - acquire: returns a constant token string (or None if headless disallowed)
    """

    name = "fake"
    _ISSUED_TOKEN = "FAKE_TOKEN"

    def validate(self, api_key: str, access_token: str) -> bool:  # noqa: D401
        return bool(access_token)

    def acquire(
        self,
        api_key: str,
        api_secret: str,
        headless: bool = False,
        interactive: bool = True,
    ) -> str | None:
        # Ignore all inputs; always issue deterministic token
        return self._ISSUED_TOKEN
