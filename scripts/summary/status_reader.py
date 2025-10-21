"""Status file reader with structured result types (Phase 0 scaffolding).

This isolates IO + decoding concerns from the loop and renderer logic so that
later phases can substitute alternative transports (SSE, IPC, etc.) without
changing domain builders.
"""
from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


# Error taxonomy kept intentionally small for now.
class StatusReadError(Exception):
    """Base class for status read failures (not found, decode, generic)."""

class StatusNotFound(StatusReadError):
    pass

class StatusDecodeError(StatusReadError):
    pass

@dataclass(frozen=True)
class StatusReadResult:
    ok: bool
    status: Mapping[str, Any] | None
    ts_read: float
    mtime: float | None
    error: StatusReadError | None = None


def read_status(path: str, *, allow_missing: bool = True) -> StatusReadResult:
    """Read a JSON status file defensively.

    Returns a StatusReadResult capturing success flag, status mapping (or None),
    file modification time, and structured error if any.
    """
    ts = time.time()
    try:
        st = os.stat(path)
    except FileNotFoundError:
        if allow_missing:
            return StatusReadResult(ok=False, status=None, ts_read=ts, mtime=None, error=StatusNotFound(path))
        raise
    except Exception as e:  # Other OS errors
        return StatusReadResult(ok=False, status=None, ts_read=ts, mtime=None, error=StatusReadError(str(e)))

    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):  # normalize to dict or None
            data = {}
        return StatusReadResult(ok=True, status=data, ts_read=ts, mtime=st.st_mtime, error=None)
    except json.JSONDecodeError as e:
        return StatusReadResult(ok=False, status=None, ts_read=ts, mtime=st.st_mtime, error=StatusDecodeError(str(e)))
    except Exception as e:  # Generic read error
        return StatusReadResult(ok=False, status=None, ts_read=ts, mtime=st.st_mtime, error=StatusReadError(str(e)))

__all__ = [
    "StatusReadError",
    "StatusNotFound",
    "StatusDecodeError",
    "StatusReadResult",
    "read_status",
]
