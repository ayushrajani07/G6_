from __future__ import annotations
from typing import Any, Dict

def alerts_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    from rich import box  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from scripts.summary.data_source import _use_panels_json, _read_panel_json
    from scripts.summary.derive import clip, fmt_hms
    from scripts.summary.env import effective_panel_width
    alerts = []
    if _use_panels_json():
        pj = _read_panel_json("alerts")
        if isinstance(pj, list):
            alerts = pj
    if not alerts and status:
        alerts = status.get("alerts") or status.get("events") or []
    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Time")
    tbl.add_column("Level")
    tbl.add_column("Component")
    tbl.add_column("Message", overflow="fold")
    count = 0
    # Pre-compute counts over full list for header
    nE = nW = nI = 0
    if isinstance(alerts, list):
        for a in alerts:
            if not isinstance(a, dict):
                continue
            lv0 = str(a.get("level", "")).upper()
            if lv0 in ("ERR", "ERROR", "CRITICAL"):
                nE += 1
            elif lv0 in ("WARN", "WARNING"):
                nW += 1
            else:
                nI += 1
        for a in reversed(alerts):  # most recent
            if not isinstance(a, dict):
                continue
            t = a.get("time") or a.get("timestamp") or ""
            lvl = a.get("level", "")
            comp = a.get("component", "")
            msg = a.get("message", "")
            ts_short = fmt_hms(t) or (str(t) if t else "")
            tbl.add_row(ts_short or "", str(lvl), str(comp), str(msg))
            count += 1
            if count >= (1 if compact else 3):
                break
    if count == 0:
        tbl.add_row("—", "—", "—", "—")
    w = effective_panel_width("alerts") or 40
    title = f"⚠️ Alerts (E:{nE} W:{nW} I:{nI})" if (nE or nW or nI) else "⚠️ Alerts"
    return Panel(tbl, title=title, border_style=("white" if low_contrast else "red"), width=w)
