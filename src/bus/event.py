from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Event:
    id: int
    ts_unix_ms: int
    type: str
    key: str | None
    payload: dict[str, Any]
    meta: dict[str, Any] | None = None

__all__ = ["Event"]
