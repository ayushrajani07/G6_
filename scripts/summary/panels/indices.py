from __future__ import annotations
from typing import Any, Dict, List, Optional


def indices_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False, loop_for_footer: Optional[Dict[str, Any]] = None) -> Any:
    # Import helpers lazily to avoid circular import at module load time
    from scripts.summary.data_source import (
        _use_panels_json,
        _read_panel_json,
        _get_indices_metrics,
    )
    from scripts.summary.derive import (
        fmt_hms,
        clip,
        fmt_timedelta_secs,
        derive_cycle,
        derive_indices,
        estimate_next_run,
    )
    from rich import box  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich.console import Group  # type: ignore
    # Prefer a rolling live stream if available under panels/indices_stream.json
    if _use_panels_json():
        pj_stream = _read_panel_json("indices_stream")
        stream_items: List[Dict[str, Any]] = []
        if isinstance(pj_stream, list):
            stream_items = pj_stream
        elif isinstance(pj_stream, dict) and isinstance(pj_stream.get("items"), list):
            stream_items = pj_stream.get("items")  # type: ignore
        if stream_items:
            tbl = Table(box=box.SIMPLE_HEAD)
            tbl.add_column("Time")
            tbl.add_column("Index", style="bold")
            tbl.add_column("Legs")
            tbl.add_column("AVG")
            tbl.add_column("Success")
            tbl.add_column("Status")
            tbl.add_column("Description", overflow="fold")
            # Show most recent first, cap to last 25
            shown = 0
            for itm in reversed(stream_items[-25:]):
                if not isinstance(itm, dict):
                    continue
                ts = fmt_hms(itm.get("time") or itm.get("ts") or itm.get("timestamp")) or ""
                idx = str(itm.get("index", itm.get("idx", "")))
                legs = itm.get("legs")
                avg = itm.get("avg") or itm.get("duration_avg") or itm.get("mean")
                succ = itm.get("success") or itm.get("success_rate")
                st = (itm.get("status") or itm.get("state") or "").upper()
                # Description appears only when non-OK
                raw_desc = itm.get("description") or itm.get("desc") or ""
                desc = (raw_desc if st != "OK" else "")
                # Color by cycle for visibility
                cyc = itm.get("cycle")
                row_style = None
                if isinstance(cyc, int):
                    palette = ["white", "cyan", "magenta", "yellow", "green", "blue"]
                    row_style = palette[cyc % len(palette)]
                # Status color
                st_style = "green" if st == "OK" else ("yellow" if st in ("WARN", "WARNING") else "red")
                tbl.add_row(ts, idx, str(legs if legs is not None else "—"), str(avg if avg is not None else "—"), str(succ if succ is not None else "—"), f"[{st_style}]{st}[/]", clip(desc), style=row_style)
                shown += 1
                if shown >= (10 if compact else 25):
                    break
            # Footer from loop metrics (cycle info)
            footer = Table.grid()
            cy = derive_cycle(status)
            avg = p95 = None
            if loop_for_footer:
                avg = loop_for_footer.get("avg")
                p95 = loop_for_footer.get("p95")
            parts = []
            if cy.get("cycle") is not None:
                parts.append(f"Cycle: {cy.get('cycle')}")
            if cy.get("last_duration") is not None:
                try:
                    ld_val = cy.get("last_duration")
                    if isinstance(ld_val, (int, float)):
                        parts.append(f"Last: {fmt_timedelta_secs(float(ld_val))}")
                except Exception:
                    pass
            if avg is not None:
                parts.append(f"Avg: {fmt_timedelta_secs(float(avg))}")
            if p95 is not None:
                parts.append(f"P95: {fmt_timedelta_secs(float(p95))}")
            nr = None
            try:
                nr = estimate_next_run(status, (status or {}).get("interval"))
            except Exception:
                nr = None
            if nr is not None:
                parts.append(f"Next: {fmt_timedelta_secs(nr)}")
            footer.add_row("[dim]" + clip(" | ".join(parts)) + "[/dim]")
            return Panel(Group(tbl, footer), title="Indices", border_style=("white" if low_contrast else "white"), expand=True)
    # Fallback to summary metrics table
    metrics = _get_indices_metrics()
    indices = derive_indices(status)
    if not indices and metrics:
        indices = list(metrics.keys())
    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Index", style="bold")
    tbl.add_column("Status")
    if metrics:
        tbl.add_column("Legs")
        tbl.add_column("Fails")
    tbl.add_column("LTP")
    tbl.add_column("Age")
    if status and isinstance(status.get("indices_detail"), dict):
        detail = status["indices_detail"]
    else:
        detail = {}
    info_fallback = status.get("indices_info") if status and isinstance(status.get("indices_info"), dict) else {}
    shown = 0
    max_rows = 4 if compact else 12
    for name in indices:
        info = detail.get(name, {}) if isinstance(detail, dict) else {}
        if not info and isinstance(info_fallback, dict):
            fb = info_fallback.get(name, {})
            if isinstance(fb, dict):
                info = {"ltp": fb.get("ltp"), "status": ("OK" if fb.get("ltp") is not None else "STALE")}
        # status priority: terminal metrics > indices_detail status
        stat = info.get("status", "—")
        if name in metrics and isinstance(metrics[name].get("status"), str):
            stat = str(metrics[name]["status"]) or stat
        ltp = info.get("ltp", "—")
        age = info.get("age", None)
        if age is None:
            age = info.get("age_sec", None)
        from scripts.summary.derive import fmt_timedelta_secs as _fmt
        age_str = _fmt(float(age)) if isinstance(age, (int, float)) else "—"
        if metrics and name in metrics:
            legs = metrics[name].get("legs")
            fails = metrics[name].get("fails")
            tbl.add_row(name, str(stat), ("—" if legs is None else str(legs)), ("—" if fails is None else str(fails)), str(ltp), age_str)
        else:
            tbl.add_row(name, str(stat), str(ltp), age_str)
        shown += 1
        if shown >= max_rows:
            break
    if not indices:
        if metrics:
            tbl.add_row("—", "—", "—", "—", "—", "—")
        else:
            tbl.add_row("—", "—", "—", "—")
    # Footer from loop metrics (fallback scenario)
    from rich.console import Group  # type: ignore
    footer = Table.grid()
    cy = derive_cycle(status)
    parts = []
    if cy.get("cycle") is not None:
        parts.append(f"Cycle: {cy.get('cycle')}")
    if cy.get("last_duration") is not None:
        try:
            ld_val = cy.get("last_duration")
            if isinstance(ld_val, (int, float)):
                parts.append(f"Last: {fmt_timedelta_secs(float(ld_val))}")
        except Exception:
            pass
    footer.add_row("[dim]" + clip(" | ".join(parts)) + "[/dim]")
    return Panel(Group(tbl, footer), title="Indices", border_style=("white" if low_contrast else "white"), expand=True)
