from __future__ import annotations

import os
from datetime import UTC
from typing import TYPE_CHECKING, Any

from scripts.summary.env_config import load_summary_env

if TYPE_CHECKING:  # pragma: no cover
    pass

def sinks_panel(status: dict[str, Any] | None, *, low_contrast: bool = False, show_title: bool = True) -> Any:
    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    from scripts.summary.data_source import (
        _read_panel_json,
        _use_panels_json,
    )
    from scripts.summary.derive import (
        clip,
        parse_iso,
    )
    def _dot(st: str) -> str:
        s = (st or "").upper()
        if s in ("OK", "HEALTHY", "READY", "SUCCESS"):
            return "[green]●[/]"
        if s in ("WARN", "WARNING", "DEGRADED"):
            return "[yellow]●[/]"
        if s:
            return "[red]●[/]"
        return "[dim]●[/]"
    # Consolidate: if panels/storage.json exists, render Storage & Backup Metrics
    if _use_panels_json():
        pj_storage = _read_panel_json("storage")
        if isinstance(pj_storage, (dict, list)):
            try:
                from rich.table import Table as RTable
                rtbl = RTable(box=box.SIMPLE_HEAD)
                rtbl.add_column("Component", style="bold")
                rtbl.add_column("Metric")
                rtbl.add_column("Value")
                rtbl.add_column("Status")
                rows = 0
                overall_status = "OK"
                total_mb = 0.0
                def parse_mb(v: Any) -> float:
                    try:
                        if isinstance(v, (int, float)):
                            return float(v)
                        s = str(v)
                        if s.lower().endswith("mb"):
                            return float(s.lower().replace("mb", "").strip())
                        if s.lower().endswith("gb"):
                            return float(s.lower().replace("gb", "").strip()) * 1024.0
                        return 0.0
                    except Exception:
                        return 0.0
                if isinstance(pj_storage, dict):
                    for k, v in pj_storage.items():
                        if isinstance(v, dict):
                            metric = str(v.get("metric", ""))
                            val = v.get("value", v.get("val", ""))
                            st = str(v.get("status", v.get("state", "")))
                            rtbl.add_row(clip(str(k)), clip(metric), clip(str(val)), _dot(st))
                            if any(t in metric.lower() for t in ["disk", "size", "storage", "usage"]):
                                total_mb += parse_mb(val)
                            if st.upper() in ("WARN", "WARNING") and overall_status == "OK":
                                overall_status = "WARN"
                            if st.upper() in ("ERR", "ERROR", "CRITICAL"):
                                overall_status = "ERROR"
                        else:
                            rtbl.add_row(clip(str(k)), "", clip(str(v)), "")
                        rows += 1
                        if rows >= 6:
                            break
                else:
                    for it in pj_storage[:6]:
                        if isinstance(it, dict):
                            metric = str(it.get("metric", ""))
                            val = it.get("value", it.get("val", ""))
                            st = str(it.get("status", it.get("state", "")))
                            rtbl.add_row(
                                clip(str(it.get("component", it.get("name", "")))),
                                clip(metric),
                                clip(str(val)),
                                _dot(st),
                            )
                            if any(t in metric.lower() for t in ["disk", "size", "storage", "usage"]):
                                total_mb += parse_mb(val)
                            if st.upper() in ("WARN", "WARNING") and overall_status == "OK":
                                overall_status = "WARN"
                            if st.upper() in ("ERR", "ERROR", "CRITICAL"):
                                overall_status = "ERROR"
                        else:
                            rtbl.add_row("", "", clip(str(it)), "")
                footer = Table.grid()
                parts: list[str] = []
                if total_mb > 0:
                    parts.append(f"Total Storage: {total_mb:.1f} MB")
                if overall_status:
                    color = (
                        "green"
                        if overall_status == "OK"
                        else ("yellow" if overall_status.startswith("WARN") else "red")
                    )
                    parts.append(f"Status: [{color}]{overall_status.lower()}[/]")
                if parts:
                    footer.add_row("[dim]" + clip(" | ".join(parts)) + "[/dim]")
                    return Panel(
                        Group(rtbl, footer),
                        title=("💾 Storage & Backup Metrics" if show_title else None),
                        border_style=("white" if low_contrast else "cyan"),
                        expand=True,
                    )
                return Panel(
                    rtbl,
                    title=("💾 Storage & Backup Metrics" if show_title else None),
                    border_style=("white" if low_contrast else "cyan"),
                    expand=True,
                )
            except Exception:
                pass
    sinks = status.get("sinks", {}) if status else {}
    if _use_panels_json():
        pj = _read_panel_json("sinks")
        if isinstance(pj, dict):
            sinks = pj
    try:
        env_sinks = load_summary_env().output_sinks_raw
    except Exception:
        env_sinks = os.getenv("G6_OUTPUT_SINKS", "stdout,logging")
    tbl = Table.grid()
    tbl.add_row(clip(f"Configured: {env_sinks}"))
    if isinstance(sinks, dict):
        for k, v in list(sinks.items())[:4]:
            last = v.get("last_write") if isinstance(v, dict) else None
            age_str = ""
            if last:
                dt = parse_iso(last)
                if dt:
                    from datetime import datetime

                    from scripts.summary.derive import fmt_hms_from_dt
                    from scripts.summary.derive import fmt_timedelta_secs as _fmt
                    now_utc = datetime.now(UTC)
                    age = (now_utc - dt).total_seconds()
                    age_str = f" ({_fmt(age)} ago)"
                    last = fmt_hms_from_dt(dt)
            tbl.add_row(clip(f"• {k}: last write {last or '—'}{age_str}"))
    return Panel(
        tbl,
        title=("Sinks" if show_title else None),
        border_style=("white" if low_contrast else "cyan"),
        expand=True,
    )
