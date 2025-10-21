from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any


@dataclass(slots=True)
class ExpiryState:
    """Shadow pipeline per-expiry state (Phase 1).

    Immutable-style usage is NOT enforced; phases may mutate in-place for
    performance, but should document side-effects. In later phases we may
    transition to returning new instances if needed for auditing.
    """
    index: str
    rule: str
    settings: Any  # CollectorSettings (kept loose to avoid import cycle)

    # Derived / evolving fields
    expiry_date: _dt.date | None = None
    strikes: list[Any] = field(default_factory=list)
    instruments: list[dict[str, Any]] = field(default_factory=list)
    enriched: dict[str, dict[str, Any]] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Structured counterpart to legacy `errors` tokens; populated in parallel.
    error_records: list[PhaseErrorRecord] = field(default_factory=list)

    def snapshot_core(self) -> dict[str, Any]:
        """Return the structural subset used for parity diff in Phase 1."""
        return {
            'expiry_date': self.expiry_date,
            'strike_count': len(self.strikes),
            'strikes': list(self.strikes),
            'instrument_count': len(self.instruments),
            'enriched_keys': len(self.enriched),
        }

if TYPE_CHECKING:  # pragma: no cover - type-only import
    from .error_records import PhaseErrorRecord  # noqa: F401

__all__ = ["ExpiryState"]
