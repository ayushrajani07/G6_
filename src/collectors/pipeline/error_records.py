from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

__all__ = ["PhaseErrorRecord"]

@dataclass(slots=True)
class PhaseErrorRecord:
    """Structured record for a phase-level error.

    Fields:
      phase            : Name of the phase function (e.g. phase_fetch)
      classification   : abort | recoverable | recoverable_exhausted | fatal | unknown
      message          : Short machine-friendly code (original token middle segment)
      detail           : Optional detail (exception string or domain tag)
      attempt          : Attempt number (1-based) inside retry loop
      timestamp        : Unix epoch seconds when captured
      outcome_token    : Legacy token persisted in state.errors (for backward compat)
    """
    phase: str
    classification: str
    message: str
    detail: str | None = None
    attempt: int = 1
    timestamp: float = field(default_factory=lambda: time.time())
    outcome_token: str = ""
    extra: dict[str, Any] | None = None
