from __future__ import annotations

"""
Resilience helpers for panel publishing and bridge I/O.

Goals:
- Guard against exceptions on panel_update/append so one bad write doesn't break the loop.
- Provide a consistent cap for stream-like panels to limit memory/IO churn.
"""
from typing import Any

DEFAULT_STREAM_CAP = 200  # global soft cap for stream panels


def safe_update(router: Any, panel: str, payload: Any) -> None:
    try:
        router.panel_update(panel, payload)
    except Exception:
        # swallow
        return


def safe_append(router: Any, panel: str, item: Any, *, cap: int | None = None, kind: str | None = None) -> None:
    try:
        c = cap if isinstance(cap, int) and cap > 0 else DEFAULT_STREAM_CAP
        router.panel_append(panel, item, cap=c, kind=kind or "stream")
    except Exception:
        return
