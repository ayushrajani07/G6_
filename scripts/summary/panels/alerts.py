from __future__ import annotations

import logging
import os
from datetime import UTC
from typing import Any

from src.error_handling import handle_ui_error
from src.utils.panel_error_utils import centralized_panel_error_handler, safe_panel_execute


@centralized_panel_error_handler("alerts_panel")
def alerts_panel(status: dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """Alerts panel with comprehensive error handling."""
    return safe_panel_execute(
        _create_alerts_panel, status, compact, low_contrast,
        error_msg="Alerts - Error Loading Data"
    )

def _create_alerts_panel(status: dict[str, Any] | None, compact: bool, low_contrast: bool) -> Any:
    """Internal implementation for alerts panel."""
    import json
    from datetime import datetime
    from pathlib import Path

    from rich import box
    from rich.console import Group
    from rich.panel import Panel
    from rich.table import Table

    from scripts.summary.data_source import _read_panel_json, _use_panels_json
    from scripts.summary.derive import clip, fmt_hms

    def _get_alerts_log_path() -> Path:
        # Read-only mode under V2 aggregation; panel must not create or write the file.
        return Path("data/panels/alerts_log.json")

    def _get_rolling_alerts_log(max_entries: int = 100) -> list[dict[str, Any]]:
        try:
            log_path = _get_alerts_log_path()
            if log_path.exists():
                # Explicit read-only to make monkeypatch-based write detection happy
                with open(log_path) as f:
                    data = json.load(f)
                    if isinstance(data, dict) and isinstance(data.get("alerts"), list):
                        return [
                            dict(it) for it in data["alerts"][-max_entries:]
                            if isinstance(it, dict)
                        ]
        except Exception as e:
            handle_ui_error(e, component="alerts_panel.log", context={"op": "read"})
            logging.warning(f"Error reading alerts log: {e}")
        return []

    # Under V2 aggregation flag the panel must be read-only (no persistence side-effects)
    FLAG_V2 = os.getenv("G6_SUMMARY_AGG_V2", "0").lower() in {"1","true","yes","on"}

    def generate_non_system_alerts(status: dict[str, Any] | None) -> list[dict[str, Any]]:  # legacy only
        # Only generate when FLAG_V2 is off; otherwise builder produced and persisted synthetic alerts
        if FLAG_V2:
            return []
        alerts: list[dict[str, Any]] = []
        try:
            now = datetime.now(UTC)
        except Exception:
            now = datetime.fromtimestamp(0, tz=UTC)
        if not status:
            return [
                {
                    "time": now.isoformat(),
                    "level": "ERROR",
                    "component": "System",
                    "message": "No status data available",
                }
            ]
        try:
            indices_detail = status.get("indices_detail", {})
            if isinstance(indices_detail, dict) and indices_detail:
                low_dq_indices = []
                for idx_name, idx_data in indices_detail.items():
                    if isinstance(idx_data, dict):
                        dq_data = idx_data.get("dq", {})
                        if isinstance(dq_data, dict):
                            score = dq_data.get("score_percent")
                            if isinstance(score, (int, float)) and score == score and score < 80:
                                low_dq_indices.append(f"{idx_name}:{score:.1f}%")
                if low_dq_indices:
                    level = "ERROR" if any(":7" in idx or ":6" in idx for idx in low_dq_indices) else "WARNING"
                    message = f"Low data quality: {', '.join(low_dq_indices[:3])}"
                    if len(low_dq_indices) > 3:
                        message += f" (+{len(low_dq_indices)-3} more)"
                    alerts.append(
                        {
                            "time": now.isoformat(),
                            "level": level,
                            "component": "Data Quality",
                            "message": message,
                        }
                    )
        except Exception:
            pass
        try:
            market = status.get("market", {})
            if isinstance(market, dict) and market.get("status") == "CLOSED":
                alerts.append(
                    {
                        "time": now.isoformat(),
                        "level": "INFO",
                        "component": "Market",
                        "message": "Market is closed",
                    }
                )
        except Exception:
            pass
        return alerts

    alerts = []

    # Get errors from centralized error handler (non-collector errors)
    try:
        from src.error_handling import get_error_handler
        handler = get_error_handler()
        centralized_alerts = handler.get_errors_for_alerts_panel(count=50)
        alerts.extend(centralized_alerts)
    except Exception as e:
        handle_ui_error(e, component="alerts_panel", context={"op": "get_centralized"})
        logging.warning(f"Could not get centralized alerts: {e}")

    if not FLAG_V2:
        if _use_panels_json():
            pj = _read_panel_json("alerts")
            if isinstance(pj, list):
                alerts.extend(pj)

    # Status-based alerts
    if status:
        if not FLAG_V2:
            status_alerts = status.get("alerts") or status.get("events") or []
            if isinstance(status_alerts, list):
                alerts.extend(status_alerts)
            alerts.extend(generate_non_system_alerts(status))
    # Under V2 we rely entirely on builder persistence; just read log
    # Always read existing rolling log; never write from panel path.
    alerts.extend(_get_rolling_alerts_log())

    # --- Severity Grouping (W4-04) ---------------------------------------------------------
    # Uses snapshot summary categories + severity mapping (added in W4-03) to produce
    # grouped counts and a short list of top categories by severity.
    enable_grouping = os.getenv("G6_ALERTS_SEVERITY_GROUPING", "1").lower() in {"1", "true", "yes", "on"}
    severity_counts: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}
    top_cats: list[tuple[str, int, str]] = []  # (category, count, severity)
    if enable_grouping:
        try:
            alerts_summary = None
            if status and isinstance(status.get("snapshot_summary"), dict):
                alerts_summary = status.get("snapshot_summary", {}).get("alerts")
            # fallback legacy key
            if not alerts_summary and status and isinstance(status.get("snapshot"), dict):
                alerts_summary = status.get("snapshot", {}).get("alerts")
            if isinstance(alerts_summary, dict):
                cats = alerts_summary.get("categories") or {}
                sev_map = alerts_summary.get("severity") or {}
                if isinstance(cats, dict) and cats:
                    buckets: dict[str, list[tuple[str, int]]] = {"critical": [], "warning": [], "info": []}
                    cap_raw = os.getenv("G6_ALERTS_SEVERITY_TOP_CAP", "3")
                    try:
                        cap = max(1, int(cap_raw))
                    except Exception:
                        cap = 3
                    for cname, cval in cats.items():
                        if not isinstance(cval, (int, float)):
                            continue
                        sev = str(sev_map.get(cname, 'info')).lower()
                        if sev not in buckets:
                            sev = 'info'
                        buckets[sev].append((cname, int(cval)))
                        severity_counts[sev] += int(cval)
                    # build top categories list
                    for sev, entries in buckets.items():
                        entries.sort(key=lambda x: x[1], reverse=True)
                        for cname, cval in entries[:cap]:
                            top_cats.append((cname, cval, sev))
        except Exception as e:
            # Fail silent - panel resilience priority
            handle_ui_error(e, component="alerts_panel", context={"op": "severity_grouping"})

    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Time", min_width=8)
    tbl.add_column("Level", min_width=8)
    tbl.add_column("Component", min_width=10)
    tbl.add_column("Message", overflow="fold")

    count = 0
    # Use more rows to fill the available alert panel space
    # Alert panel has 70% of right column height, so significantly more space available
    max_rows = 4 if compact else 15

    # Count alert levels
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

        # Sort by timestamp (most recent first)
        try:
            sorted_alerts = sorted(alerts, key=lambda x: x.get("time", ""), reverse=True)
        except Exception as e:
            handle_ui_error(e, component="alerts_panel", context={"op": "sort"})
            sorted_alerts = alerts

        for a in sorted_alerts[:max_rows]:
            if not isinstance(a, dict):
                continue
            t = a.get("time") or a.get("timestamp") or ""
            lvl = str(a.get("level", "")).upper()
            comp = str(a.get("component", ""))
            msg = str(a.get("message", ""))

            ts_short = fmt_hms(t) or (str(t)[:8] if t else "")

            # Color code levels
            if lvl in ("ERR", "ERROR", "CRITICAL"):
                lvl_display = f"[red]{lvl}[/]"
            elif lvl in ("WARN", "WARNING"):
                lvl_display = f"[yellow]{lvl}[/]"
            else:
                lvl_display = f"[blue]{lvl}[/]"

            tbl.add_row(ts_short, lvl_display, clip(comp, 12), clip(msg, 40))
            count += 1

    # Fill empty rows
    while count < max_rows:
        tbl.add_row("—", "—", "—", "—")
        count += 1

    # Footer with alert summary
    footer = Table.grid()
    if nE + nW + nI > 0:
        summary = []
        if nE > 0:
            summary.append(f"[red]{nE} Critical[/]")
        if nW > 0:
            summary.append(f"[yellow]{nW} Warning[/]")
        if nI > 0:
            summary.append(f"[blue]{nI} Info[/]")
        footer.add_row(f"[dim]Active: {' | '.join(summary)}[/dim]")
        # Severity grouping footer lines (only if we have category counts)
        if enable_grouping and any(severity_counts.values()):
            parts = []
            if severity_counts['critical']:
                parts.append(f"[red]{severity_counts['critical']} crit(cat)")
            if severity_counts['warning']:
                parts.append(f"[yellow]{severity_counts['warning']} warn(cat)")
            if severity_counts['info']:
                parts.append(f"[blue]{severity_counts['info']} info(cat)")
            if parts:
                footer.add_row(f"[dim]Categories: {' '.join(parts)}[/dim]")
            if top_cats:
                frag = []
                # limit overall number of displayed top categories for readability
                for name, val, sev in top_cats[:6]:
                    color = 'red' if sev == 'critical' else ('yellow' if sev == 'warning' else 'blue')
                    frag.append(f"[{color}]{name}:{val}[/]")
                footer.add_row(f"[dim]Top: {' '.join(frag)}[/dim]")
    else:
        footer.add_row("[green dim]No active alerts - All systems nominal[/]")

    title = "🚨 Alerts"
    border_color = "red" if nE > 0 else ("yellow" if nW > 0 else "green")

    return Panel(
        Group(tbl, footer),
        title=title,
        border_style=("white" if low_contrast else border_color),
        expand=True
    )
