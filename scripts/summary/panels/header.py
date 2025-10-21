from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    pass

def header_panel(
    app_title: str,
    version: str,
    indices: list[str],
    *,
    low_contrast: bool = False,
    status: dict[str, Any] | None = None,
    interval: float | None = None,
) -> Any:
    from rich import box
    from rich.panel import Panel
    from rich.table import Table

    from scripts.summary.derive import (
        clip,
        derive_market_summary,
        fmt_hms_from_dt,
        fmt_timedelta_secs,
        is_market_hours_ist,
        next_market_open_ist,
    )
    now = fmt_hms_from_dt(datetime.now(UTC))
    ind_txt = ", ".join(indices) if indices else "—"
    state, extra = derive_market_summary(status or {})
    try:
        if is_market_hours_ist():
            state = "OPEN"
            extra = ""
        elif not extra:
            nxt = next_market_open_ist()
            if nxt is not None:
                nxt_utc = nxt.astimezone(UTC)
                delta = (nxt_utc - datetime.now(UTC)).total_seconds()
                extra = f"next open: {fmt_hms_from_dt(nxt_utc)} (in {fmt_timedelta_secs(delta)})"
    except Exception:
        pass
    t = Table.grid(expand=True)
    t.add_column(justify="left")
    t.add_column(justify="center")
    t.add_column(justify="right")
    # Data source indicator
    try:
        from scripts.summary.data_source import _use_panels_json
        src = "Panels" if _use_panels_json() else "Status"
    except Exception:
        src = "—"
    # First row: indices + time (stable width, no extra lines)
    t.add_row("", f"[dim]Indices:[/] {ind_txt}", f"IST {now}")
    mid_parts = [f"State: [bold]{state}[/]"]
    if interval:
        try:
            mid_parts.append(f"Cycle Interval: {int(float(interval))}s")
        except Exception:
            mid_parts.append(f"Cycle Interval: {interval}s")
    # Snapshot integrity badge (need_full indicator)
    try:
        # Default: show indicator unless explicitly disabled via env
        show_flag = os.getenv("G6_SUMMARY_SHOW_NEED_FULL", "").strip().lower()
        show_indicator = show_flag not in ("0", "off", "no", "false")
        meta = status.get("panel_push_meta") if (status and isinstance(status, dict)) else None
        if show_indicator and isinstance(meta, dict) and meta.get("need_full"):
            reason = meta.get("need_full_reason") or "snapshot_required"
            gen = meta.get("panel_generation")
            badge_core = "FULL SNAPSHOT REQUIRED"
            # Only append reason if it adds clarity beyond default
            if reason and reason not in ("snapshot_required",):
                badge_core += f" ({reason})"
            if gen is not None:
                badge_core += f" g={gen}"
            # High contrast badge plus plain token for downstream parsing/tests
            styled = f"[bold white on red] {badge_core} [/]"
            sentinel = "FULL_SNAPSHOT_REQUIRED"
            # Prepend so even if later clipping occurs, likely survives
            mid_parts.insert(0, f"{sentinel} {styled}")
    except Exception:
        # Non-fatal: never break header rendering
        pass
    if extra:
        mid_parts.append(extra)
    up_txt = "—"
    import time as _t
    try:
        start_ts = float(os.getenv("G6_PROCESS_START_TS", "0") or 0)
        if start_ts > 0:
            up_txt = fmt_timedelta_secs(max(0.0, _t.time() - start_ts))
    except Exception:
        up_txt = "—"
    # Second row: market state + interval, and show both source and uptime for clarity
    right_parts = []
    if src and src != "—":
        right_parts.append(f"[dim]Source:[/] {src}")
    if up_txt and up_txt != "—":
        right_parts.append(f"[dim]Uptime:[/] {up_txt}")
    right = "  |  ".join(right_parts) if right_parts else ""
    t.add_row("", clip(" | ".join(mid_parts)), right)
    # Ensure a stable panel title
    title_txt = "Overview"
    return Panel(t, box=box.ROUNDED, title=title_txt, border_style=("white" if low_contrast else "cyan"))
