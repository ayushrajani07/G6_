from __future__ import annotations

from typing import Any


def links_panel(status_file: str, metrics_url: str | None, *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel
    from rich.table import Table

    from scripts.summary.data_source import _read_panel_json, _use_panels_json
    from scripts.summary.derive import clip
    from scripts.summary.env import effective_panel_width
    tbl = Table.grid()
    if _use_panels_json():
        pj = _read_panel_json("links")
        if isinstance(pj, dict) and isinstance(pj.get("metrics"), str):
            metrics_url = pj.get("metrics")
    tbl.add_row(clip(f"Status: {status_file}"))
    if metrics_url:
        tbl.add_row(clip(f"Metrics: {metrics_url}"))
    w = effective_panel_width("links")
    return Panel(tbl, title="🔗 Links", border_style=("white" if low_contrast else "dim"), width=w)
