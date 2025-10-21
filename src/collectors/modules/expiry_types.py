"""Typed structures for expiry processing (draft, phase 2).

Introduces provisional TypedDicts for expiry record and metrics payload to
progressively tighten type checking without forcing immediate refactors of
all producer/consumer sites. These are opt-in: code can import the aliases
under TYPE_CHECKING to avoid runtime dependency on typing_extensions.
"""
from __future__ import annotations

from typing import Any, NotRequired, TypedDict

# NOTE: We keep fields intentionally permissive (Optional / unions) to match
# current dynamic dict usage; later passes can narrow once all writers are
# aligned.

class ExpiryRecord(TypedDict, total=False):
    rule: str
    expiry_date: Any | None
    strikes_requested: int
    instruments: int
    options: int
    failed: bool
    pcr: int | str | None
    strike_coverage: int | None
    field_coverage: int | None
    status: str | None
    # Additional dynamically attached fields (kept loose for now)
    issues: NotRequired[list[str]]
    notes: NotRequired[str]

class MetricsPayload(TypedDict, total=False):
    expiry_code: str
    pcr: int | float | None
    instruments: NotRequired[int]
    options: NotRequired[int]
    strike_coverage: NotRequired[int]
    field_coverage: NotRequired[int]
    status: NotRequired[str]
    raw: NotRequired[dict[str, Any]]

# Public re-export convenience
__all__ = ["ExpiryRecord", "MetricsPayload"]
