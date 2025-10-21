from __future__ import annotations

"""Recovery strategy abstractions (Phase 2 scaffolding).

Currently unused by legacy main path; shadow pipeline can experiment with
pluggable strategies in later patches. Provided now to anchor future tests and
reduce churn when wired in.
"""
from typing import Any, Protocol


class RecoveryStrategy(Protocol):  # pragma: no cover - interface
    def attempt_salvage(self, ctx: Any, settings: Any, state: Any) -> bool: ...

class DefaultRecoveryStrategy:
    def attempt_salvage(self, ctx: Any, settings: Any, state: Any) -> bool:  # pragma: no cover - simple stub
        # Delegate to phase_salvage semantics (already executed); returns True if salvage_applied meta present.
        return bool(getattr(state, 'meta', {}).get('salvage_applied'))

__all__ = ["RecoveryStrategy", "DefaultRecoveryStrategy"]
