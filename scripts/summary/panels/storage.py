from __future__ import annotations
from typing import Any, Dict
import os

def sinks_panel(status: Dict[str, Any] | None, *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich import box  # type: ignore
    from rich.console import Group  # type: ignore
    from scripts.summary.data_source import (
        _use_panels_json,
        _read_panel_json,
    )
    from scripts.summary.derive import (
        clip,
        parse_iso,
        fmt_timedelta_secs,
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
                from rich.table import Table as RTable  # type: ignore
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
                            rtbl.add_row(clip(str(it.get("component", it.get("name", "")))), clip(metric), clip(str(val)), _dot(st))
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
                    color = "green" if overall_status == "OK" else ("yellow" if overall_status.startswith("WARN") else "red")
                    parts.append(f"Status: [{color}]{overall_status.lower()}[/]")
                if parts:
                    footer.add_row("[dim]" + clip(" | ".join(parts)) + "[/dim]")
                    return Panel(Group(rtbl, footer), title="💾 Storage & Backup Metrics", border_style=("white" if low_contrast else "cyan"), expand=True)
                return Panel(rtbl, title="💾 Storage & Backup Metrics", border_style=("white" if low_contrast else "cyan"), expand=True)
            except Exception:
                pass
    sinks = status.get("sinks", {}) if status else {}
    if _use_panels_json():
        pj = _read_panel_json("sinks")
        if isinstance(pj, dict):
            sinks = pj
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
                    from datetime import datetime, timezone
                    from scripts.summary.derive import fmt_hms_from_dt, fmt_timedelta_secs as _fmt
                    now_utc = datetime.now(timezone.utc)
                    age = (now_utc - dt).total_seconds()
                    age_str = f" ({_fmt(age)} ago)"
                    last = fmt_hms_from_dt(dt)
            tbl.add_row(clip(f"• {k}: last write {last or '—'}{age_str}"))
    return Panel(tbl, title="Sinks", border_style=("white" if low_contrast else "cyan"), expand=True)
