from __future__ import annotations
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

def header_panel(app_title: str, version: str, indices: List[str], *, low_contrast: bool = False, status: Optional[Dict[str, Any]] = None, interval: Optional[float] = None) -> Any:
    from rich import box  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from scripts.summary.derive import (
        fmt_hms_from_dt,
        derive_market_summary,
        is_market_hours_ist,
        next_market_open_ist,
        fmt_timedelta_secs,
        clip,
    )
    now = fmt_hms_from_dt(datetime.now(timezone.utc))
    ind_txt = ", ".join(indices) if indices else "—"
    state, extra = derive_market_summary(status or {})
    try:
        if is_market_hours_ist():
            state = "OPEN"
            extra = ""
        elif not extra:
            nxt = next_market_open_ist()
            if nxt is not None:
                nxt_utc = nxt.astimezone(timezone.utc)
                delta = (nxt_utc - datetime.now(timezone.utc)).total_seconds()
                extra = f"next open: {nxt_utc.isoformat().replace('+00:00','Z')} (in {fmt_timedelta_secs(delta)})"
    except Exception:
        pass
    t = Table.grid(expand=True)
    t.add_column(justify="left")
    t.add_column(justify="center")
    t.add_column(justify="right")
    # Data source indicator
    try:
        from scripts.summary.data_source import _use_panels_json  # type: ignore
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
    if extra:
        mid_parts.append(extra)
    up_txt = "—"
    import os, time as _t
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
