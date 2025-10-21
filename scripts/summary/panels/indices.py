from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

from src.error_handling import handle_ui_error
from src.utils.panel_error_utils import centralized_panel_error_handler


def get_collector_errors_for_stream() -> list[dict[str, Any]]:
    """Get collector errors from centralized error handler for live stream."""
    try:
        from src.error_handling import get_error_handler
        handler = get_error_handler()
        res = handler.get_errors_for_indices_panel(count=10)
        out: list[dict[str, Any]] = []
        if isinstance(res, list):
            out = [dict(it) for it in res if isinstance(it, dict)]
        return out
    except Exception as e:
        handle_ui_error(e, component="indices_panel", context={"op": "get_collector_errors"})
        logging.warning(f"Could not get collector errors: {e}")
        return []

@centralized_panel_error_handler("indices_panel")
def indices_panel(
    status: dict[str, Any] | None,
    *,
    compact: bool = False,
    low_contrast: bool = False,
    loop_for_footer: dict[str, Any] | None = None,
) -> Any:
    # Import helpers lazily to avoid circular import at module load time
    from scripts.summary.data_source import (
        _get_indices_metrics,
        _read_panel_json,
        _use_panels_json,
    )
    from scripts.summary.derive import (
        clip,
        derive_cycle,
        derive_indices,
        estimate_next_run,
        fmt_hms,
        fmt_timedelta_secs,
    )
    # Guard rich imports (environment may run without rich for plain output tests)
    try:  # narrow scope; if unavailable let ImportError propagate to centralized handler
        from rich import box  # noqa: F401
        from rich.console import Group  # noqa: F401
        from rich.panel import Panel  # noqa: F401
        from rich.table import Table  # noqa: F401
    except Exception as _imp_err:  # pragma: no cover - defensive
        handle_ui_error(_imp_err, component="indices_panel", context={"op": "import_rich"})
        # Re-raise so centralized_panel_error_handler can surface fallback
        raise
    # Prefer a rolling live stream if available under panels/indices_stream.json
    if _use_panels_json():
        pj_stream = _read_panel_json("indices_stream")
        stream_items: list[dict[str, Any]] = []
        if isinstance(pj_stream, list):
            stream_items = pj_stream
        elif isinstance(pj_stream, dict) and isinstance(pj_stream.get("items"), list):
            # Items list comes from serialized panel JSON shape {"items": [...]}; validate type
            maybe_items = pj_stream.get("items")
            if isinstance(maybe_items, list):
                stream_items = maybe_items
        if stream_items:
            # Filter items to only enabled indices based on current config/status
            try:
                enabled_set = set()
                # Prefer indices present in runtime status (derive_indices respects config/run-time outputs)
                from scripts.summary.derive import derive_indices as _dinds
                inds = _dinds(status)
                for s in inds:
                    try:
                        if isinstance(s, str) and s.strip():
                            enabled_set.add(s.strip().upper())
                    except Exception:  # noqa: PERF203 - continue on bad item without aborting filter
                        continue
                # If still empty, attempt to read enabled symbols from normalized config via unified source
                if not enabled_set:
                    try:
                        from src.data_access.unified_source import UnifiedDataSource
                        uds = UnifiedDataSource()
                        cfg = uds._read_status()  # direct read to avoid cache shape
                        if isinstance(cfg, dict):
                            # Use indices_detail keys if present
                            if isinstance(cfg.get('indices_detail'), dict):
                                for k in cfg['indices_detail'].keys():
                                    enabled_set.add(str(k).upper())
                            elif isinstance(cfg.get('indices'), dict):
                                for k in cfg['indices'].keys():
                                    enabled_set.add(str(k).upper())
                    except Exception:
                        pass
                if enabled_set:
                    stream_items = [
                        it
                        for it in stream_items
                        if isinstance(it, dict)
                        and str(it.get('index', it.get('idx', ''))).upper() in enabled_set
                    ]
            except Exception:
                pass
            # Fetch recent collector errors and index them for quick lookup per index/cycle/time window
            collector_errors = get_collector_errors_for_stream()
            # Build indices for reasons: by (index, cycle) and by (index, recent-window)
            errors_by_idx_cycle: dict[tuple, list[str]] = {}
            errors_by_idx: dict[str, list[dict[str, Any]]] = {}
            try:
                from scripts.summary.derive import parse_iso as _piso
                for err in (collector_errors or []):
                    try:
                        idx = str(err.get("index") or "").upper()
                        if not idx:
                            continue
                        cyc = err.get("cycle")
                        desc = str(err.get("description") or "")
                        if isinstance(cyc, int):
                            errors_by_idx_cycle.setdefault((idx, cyc), []).append(desc)
                        # Keep a time-ordered list for recent time matching
                        e_dt = _piso(err.get("time")) if err.get("time") else None
                        errors_by_idx.setdefault(idx, []).append({"desc": desc, "dt": e_dt})
                    except Exception:
                        continue
                # Sort each list newest-first
                for _arr in errors_by_idx.values():
                    try:
                        _arr.sort(key=lambda x: (x.get("dt") or ""), reverse=True)
                    except Exception:  # noqa: PERF203 - tolerate sort failure to keep panel resilient
                        pass
            except Exception:
                errors_by_idx_cycle = {}
                errors_by_idx = {}

            # Sort stream items by timestamp (most recent first)
            try:
                from scripts.summary.derive import parse_iso
                stream_items.sort(key=lambda x: parse_iso(x.get("time", "")) or x.get("time", ""), reverse=True)
            except Exception as e:
                handle_ui_error(e, component="indices_panel", context={"op": "sort_stream"})
                stream_items.sort(key=lambda x: x.get("time", ""), reverse=True)

            # DQ thresholds via centralized registry (env overrides handled there)
            from scripts.summary.thresholds import T  # lightweight import
            dq_warn = T.dq_warn
            dq_err = T.dq_error
            # Compute staleness of the stream: latest item timestamp age
            latest_age_sec: float | None = None
            try:
                from datetime import datetime

                from scripts.summary.derive import parse_iso
                latest_dt = None
                for it in stream_items:
                    if not isinstance(it, dict):
                        continue
                    ts_val = it.get("time") or it.get("ts") or it.get("timestamp")
                    dt = parse_iso(ts_val)
                    if dt is not None:
                        if latest_dt is None or dt > latest_dt:
                            latest_dt = dt
                if latest_dt is not None:
                    latest_age_sec = (datetime.now(UTC) - latest_dt).total_seconds()
            except Exception:
                latest_age_sec = None
            tbl = Table(box=box.SIMPLE_HEAD)
            tbl.add_column("Time")
            tbl.add_column("Index", style="bold")
            tbl.add_column("DQ%")
            tbl.add_column("Legs")
            tbl.add_column("Success")
            tbl.add_column("Status")
            tbl.add_column("Description", overflow="fold")
            # Show most recent first, cap to fixed rows to keep height stable
            max_rows = (10 + 4) if compact else (20 + 4)
            # Take a slice large enough and then truncate visually to max_rows
            recent = stream_items[:(max_rows * 2)]
            shown = 0
            # Group by cycle when present; otherwise by timestamp string
            last_group_key: str | None = None
            group_idx = 0
            for itm in recent:
                if not isinstance(itm, dict):
                    continue
                raw_ts = itm.get("time") or itm.get("ts") or itm.get("timestamp")
                ts = fmt_hms(raw_ts) or ""
                idx = str(itm.get("index", itm.get("idx", ""))).upper()

                # Normal DQ fields for regular items
                dq_score = itm.get("dq_score")
                if isinstance(dq_score, (int, float)):
                    if dq_score < dq_err:
                        dq_style = "red"
                    elif dq_score < dq_warn:
                        dq_style = "yellow"
                    else:
                        dq_style = "green"
                    dq_text = f"[{dq_style}]{float(dq_score):.1f}%[/]"
                else:
                    dq_text = "—"

                # Legs: prefer current-cycle legs from stream item only
                legs_val = itm.get("legs")
                if isinstance(legs_val, (int, float)):
                    legs = str(int(legs_val))
                else:
                    # Try parsing numeric strings safely
                    try:
                        if isinstance(legs_val, str) and legs_val.strip().isdigit():
                            legs = str(int(legs_val.strip()))
                        else:
                            legs = "—"
                    except Exception:
                        legs = "—"

                succ = itm.get("success") or itm.get("success_rate")
                st = (itm.get("status") or itm.get("state") or "").upper()
                # Build precise description that explains low success/DQ
                raw_desc = itm.get("description") or itm.get("desc") or ""
                status_reason = itm.get("status_reason") or ""
                desc_parts: list[str] = []
                # Track DQ degradation for visibility (without repeating numbers)
                dq_degraded = False
                try:
                    # Prefer labeled DQ issues if available (dq_labels)
                    dq_labels = itm.get("dq_labels")
                    if isinstance(dq_labels, list) and dq_labels:
                        labels_str = ", ".join([str(x) for x in dq_labels[:3]])
                        if labels_str:
                            desc_parts.append(f"DQ: {labels_str}")
                    else:
                        # Fallback to any dq_issues list (legacy) or set degraded flag on numeric
                        dq_issues = itm.get("dq_issues")
                        if isinstance(dq_issues, list) and dq_issues:
                            issues_str = ", ".join([str(x) for x in dq_issues[:3]])
                            if issues_str:
                                desc_parts.append(f"DQ: {issues_str}")
                        elif isinstance(dq_issues, (int, float)):
                            if int(dq_issues) > 0:
                                dq_degraded = True
                except Exception:
                    pass
                # Attach recent collector error reasons matching index & cycle/time
                try:
                    from scripts.summary.derive import parse_iso as _piso
                    cyc_val = itm.get("cycle") if isinstance(itm.get("cycle"), int) else None
                    if isinstance(cyc_val, int):
                        reasons = list(
                            dict.fromkeys(
                                errors_by_idx_cycle.get((idx, cyc_val), [])
                            )
                        )  # unique preserve order
                        if reasons:
                            desc_parts.append("Errors: " + "; ".join(reasons[:2]))
                    # If still empty, try recent time window match (±90s)
                    if not desc_parts:
                        it_dt = _piso(raw_ts) if raw_ts else None
                        if it_dt is not None and idx in errors_by_idx:
                            recent_descs: list[str] = []
                            for _e in errors_by_idx.get(idx, [])[:5]:
                                _e_dt = _e.get("dt")
                                try:
                                    if _e_dt is not None:
                                        _diff = abs((it_dt - _e_dt).total_seconds())
                                        if _diff <= 90:
                                            recent_descs.append(str(_e.get("desc") or ""))
                                except Exception:
                                    continue
                            if recent_descs:
                                uniq_recent = list(dict.fromkeys([d for d in recent_descs if d]))
                                if uniq_recent:
                                    desc_parts.append("Errors: " + "; ".join(uniq_recent[:2]))
                except Exception:
                    pass
                # Fallback to any existing description when not OK
                if not desc_parts and st != "OK":
                    # Prefer explicit status_reason from stream item, but ignore generic success mentions
                    if status_reason and ("success " not in str(status_reason).lower()):
                        desc_parts.append(str(status_reason))
                    elif raw_desc:
                        # Avoid repeating generic success messages
                        if "success " in str(raw_desc).lower():
                            pass
                        else:
                            desc_parts.append(str(raw_desc))
                # Determine if DQ% is degraded by thresholds (for visibility)
                try:
                    if isinstance(dq_score, (int, float)):
                        if float(dq_score) < dq_warn:
                            dq_degraded = True or dq_degraded
                except Exception:
                    pass
                # Show description only when we have a concrete reason to display
                show_desc = len([d for d in desc_parts if d]) > 0
                # Also allow showing when status isn't OK and we have any non-generic hint
                if not show_desc and st != "OK":
                    show_desc = len([d for d in desc_parts if d]) > 0
                # If DQ is degraded but we don't have specifics yet, try to surface nearby data_validation errors
                if not show_desc and dq_degraded:
                    try:
                        # Try recent errors again with preference for data_validation category (already in desc text)
                        if idx in errors_by_idx:
                            candidates: list[str] = []
                            for _e in errors_by_idx.get(idx, [])[:5]:
                                _txt = str(_e.get("desc") or "")
                                if _txt.lower().startswith("data_validation"):
                                    candidates.append(_txt)
                            if candidates:
                                uniq_candidates = list(dict.fromkeys(candidates))
                                if uniq_candidates:
                                    desc_parts.append("Errors: " + "; ".join(uniq_candidates[:2]))
                                    show_desc = True
                    except Exception:
                        pass
                desc = clip(" | ".join([d for d in desc_parts if d])) if show_desc else ""
                # Color by cycle for visibility
                cyc = itm.get("cycle")
                # Determine grouping key for color/separator: prefer cycle; else time string
                if isinstance(cyc, int):
                    group_key: str = f"cyc:{cyc}"
                else:
                    group_key = f"ts:{str(raw_ts)}"
                # Assign bright color per group for visibility
                palette = [
                    "bright_white",
                    "bright_cyan",
                    "bright_magenta",
                    "bright_yellow",
                    "bright_green",
                    "bright_blue",
                ]
                if last_group_key is None:
                    row_style = palette[group_idx % len(palette)]
                else:
                    row_style = palette[group_idx % len(palette)]
                # Status color
                st_style = "green" if st == "OK" else ("yellow" if st in ("WARN", "WARNING") else "red")
                # Insert a blank separator row at group boundaries (cycle/time changes)
                if last_group_key is not None and group_key != last_group_key and shown < max_rows:
                    tbl.add_row("", "", "", "", "", "", "")
                    shown += 1
                    group_idx += 1
                    row_style = palette[group_idx % len(palette)]
                tbl.add_row(
                    ts,
                    idx,
                    dq_text,
                    str(legs if legs is not None else "—"),
                    str(succ if succ is not None else "—"),
                    f"[{st_style}]{st}[/]",
                    clip(desc),
                    style=row_style,
                )
                shown += 1
                last_group_key = group_key
                if shown >= max_rows:
                    break
            # Pad to fixed height to avoid flicker/row shifting
            while shown < max_rows:
                tbl.add_row("", "", "—", "—", "—", "", "")
                shown += 1
            # Footer: prefer stream-derived cycle (gated cadence), fallback to status loop
            footer = Table.grid()
            cy = derive_cycle(status)
            try:
                # Determine latest cycle present in items
                latest_cycle: int | None = None
                for it in stream_items:
                    if isinstance(it, dict) and isinstance(it.get("cycle"), int):
                        c_val = it.get("cycle")
                        if isinstance(c_val, int) and (latest_cycle is None or c_val > latest_cycle):
                            latest_cycle = c_val
                if isinstance(latest_cycle, int):
                    cy["cycle"] = latest_cycle
            except Exception:
                pass
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
            except Exception as e:
                handle_ui_error(e, component="indices_panel", context={"op": "estimate_next_run"})
                nr = None
            if nr is not None:
                parts.append(f"Next: {fmt_timedelta_secs(nr)}")
            footer.add_row("[dim]" + clip(" | ".join(parts)) + "[/dim]")
            # Stream freshness indicator to highlight when the live feed is idle/stale
            try:
                if isinstance(latest_age_sec, (int, float)):
                    # Staleness thresholds from registry
                    from scripts.summary.thresholds import T as _T
                    stale_warn = _T.stream_stale_warn_sec
                    stale_err = _T.stream_stale_error_sec
                    if latest_age_sec >= stale_err:
                        footer.add_row(f"[red]Stream idle: {fmt_timedelta_secs(latest_age_sec)}[/]")
                    elif latest_age_sec >= stale_warn:
                        footer.add_row(f"[yellow]Stream idle: {fmt_timedelta_secs(latest_age_sec)}[/]")
            except Exception:
                pass
            # DQ summary chip by latest per index
            try:
                latest: dict[str, dict[str, Any]] = {}
                for itm in stream_items:
                    if isinstance(itm, dict):
                        idx_name = str(itm.get("index", itm.get("idx", "")))
                        if idx_name:
                            latest[idx_name] = itm
                g = y = r = 0
                for it in latest.values():
                    sc = it.get("dq_score")
                    if isinstance(sc, (int, float)):
                        if sc < dq_err:
                            r += 1
                        elif sc < dq_warn:
                            y += 1
                        else:
                            g += 1
                if (g + y + r) > 0:
                    footer.add_row(f"[dim]DQ: {g}/{y}/{r}[/dim]")
            except Exception as e:
                handle_ui_error(e, component="indices_panel", context={"op": "dq_summary"})
            # DQ legend
            footer.add_row(
                f"[dim]DQ% legend: ≥{dq_warn:.0f}%, ≥{dq_err:.0f}%, <{dq_err:.0f}% | Issues > 0 shown in red[/dim]"
            )
            return Panel(
                Group(tbl, footer),
                title="Indices",
                border_style=("white" if low_contrast else "white"),
                expand=True,
            )
    # Fallback to summary metrics table
    metrics = _get_indices_metrics()
    indices = derive_indices(status)
    if not indices and metrics:
        indices = list(metrics.keys())
    # Thresholds from registry
    from scripts.summary.thresholds import T as _T2
    dq_warn = _T2.dq_warn
    dq_err = _T2.dq_error
    tbl = Table(box=box.SIMPLE_HEAD)
    tbl.add_column("Index", style="bold")
    tbl.add_column("Status")
    tbl.add_column("DQ%")
    # Always add legs column for consistency
    tbl.add_column("Legs")
    if metrics:
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
        # DQ
        dq_score_val = None
        try:
            dq = info.get("dq") if isinstance(info, dict) else None
            if isinstance(dq, dict):
                dq_score_val = dq.get("score_percent")
        except Exception:
            pass
        if isinstance(dq_score_val, (int, float)):
            if float(dq_score_val) < dq_err:
                dq_style = "red"
            elif float(dq_score_val) < dq_warn:
                dq_style = "yellow"
            else:
                dq_style = "green"
            dq_score_text = f"[{dq_style}]{float(dq_score_val):.1f}%[/]"
        else:
            dq_score_text = "—"
        ltp = info.get("ltp", "—")
        age = info.get("age", None)
        if age is None:
            age = info.get("age_sec", None)
        from scripts.summary.derive import fmt_timedelta_secs as _fmt
        age_str = _fmt(float(age)) if isinstance(age, (int, float)) else "—"
        # Calculate average legs per cycle from cumulative legs
        legs_cumulative = info.get("legs") if isinstance(info, dict) else None
        cycle_count = None
        if status and isinstance(status.get("loop"), dict):
            cycle_count = status["loop"].get("cycle")

        # Calculate average legs per cycle
        avg_legs = None
        if legs_cumulative is not None and cycle_count is not None and cycle_count > 0:
            avg_legs = legs_cumulative / cycle_count

        if metrics and name in metrics:
            # Try to get current cycle legs (if available from enhanced metrics)
            legs_current = metrics[name].get("legs")

            # Format legs as: current_cycle_legs (average_per_cycle)
            if legs_current is not None and avg_legs is not None:
                legs_display = f"{legs_current} ({avg_legs:.0f})"
            elif legs_current is not None:
                legs_display = str(legs_current)
            elif avg_legs is not None:
                legs_display = f"— ({avg_legs:.0f})"
            else:
                legs_display = "—"

            fails = metrics[name].get("fails")
            tbl.add_row(
                name,
                str(stat),
                dq_score_text,
                legs_display,
                ("—" if fails is None else str(fails)),
                str(ltp),
                age_str,
            )
        else:
            # For non-metrics fallback, show cumulative legs with average in brackets
            if legs_cumulative is not None and avg_legs is not None:
                legs_display = f"{legs_cumulative} ({avg_legs:.0f})"
            elif avg_legs is not None:
                legs_display = f"— ({avg_legs:.0f})"
            else:
                legs_display = "—"
            tbl.add_row(name, str(stat), dq_score_text, legs_display, str(ltp), age_str)
        shown += 1
        if shown >= max_rows:
            break
    if not indices:
        if metrics:
            tbl.add_row("—", "—", "—", "—", "—", "—", "—")
        else:
            tbl.add_row("—", "—", "—", "—", "—")
    # Footer from loop metrics (fallback scenario) - Group already imported above
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
    # DQ legend
    footer.add_row(
        f"[dim]DQ% legend: ≥{dq_warn:.0f}%, ≥{dq_err:.0f}%, <{dq_err:.0f}% | Issues > 0 shown in red[/dim]"
    )
    return Panel(
        Group(tbl, footer),
        title="Indices",
        border_style=("white" if low_contrast else "white"),
        expand=True,
    )
