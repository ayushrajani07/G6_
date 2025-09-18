from __future__ import annotations
from typing import Any, Dict

def analytics_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich import box  # type: ignore
    from scripts.summary.data_source import _use_panels_json, _read_panel_json
    from scripts.summary.derive import clip
    data = None
    if _use_panels_json():
        pj = _read_panel_json("analytics")
        if isinstance(pj, dict):
            data = pj
    if data is None:
        data = (status or {}).get("analytics") if status else None
    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Index", style="bold")
    tbl.add_column("PCR")
    tbl.add_column("Max Pain")
    shown = 0
    if isinstance(data, dict):
        # Case 1: per-index dict mapping
        for name, vals in data.items():
            if isinstance(vals, dict):
                pcr = vals.get("pcr", "—")
                mp = vals.get("max_pain", "—")
                tbl.add_row(clip(str(name)), clip(str(pcr)), clip(str(mp)))
                shown += 1
                if shown >= (3 if compact else 6):
                    break
        # Case 2: global metrics
        if shown == 0:
            if "max_pain" in data and isinstance(data["max_pain"], dict):
                for name, mp in data["max_pain"].items():
                    tbl.add_row(clip(str(name)), "—", clip(str(mp)))
                    shown += 1
                    if shown >= (3 if compact else 6):
                        break
            elif "pcr" in data:
                tbl.add_row("—", clip(str(data["pcr"])), "—")
                shown = 1
    if shown == 0:
        tbl.add_row("—", "—", "—")
    return Panel(tbl, title="Analytics", border_style=("white" if low_contrast else "yellow"), expand=True)
