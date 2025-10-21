"""Structured event logging helpers for provider (A19)."""
from __future__ import annotations

import logging
from typing import Any

__all__ = ["emit_event"]

def emit_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured provider event.

    Format: event key=value key=value (values already stringified lightly)
    Intended for easy grep / downstream parsing.
    """
    try:
        parts = [event]
        for k, v in fields.items():
            if isinstance(v, (list, tuple)):
                v = ",".join(str(x) for x in v)
            parts.append(f"{k}={v}")
        logger.info(" ".join(parts))
    except Exception:  # pragma: no cover - defensive
        logger.info(event)
