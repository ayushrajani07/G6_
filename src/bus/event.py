from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional

@dataclass(slots=True)
class Event:
    id: int
    ts_unix_ms: int
    type: str
    key: Optional[str]
    payload: Dict[str, Any]
    meta: Optional[Dict[str, Any]] = None

__all__ = ["Event"]
