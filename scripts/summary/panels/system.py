from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Any

from scripts.summary.env_config import load_summary_env

if TYPE_CHECKING:  # pragma: no cover
    pass

def health_panel(
    status: dict[str, Any] | None,
    *,
    low_contrast: bool = False,
    compact: bool = False,
    show_title: bool = True,
) -> Any:
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
        collect_resources,
        derive_health,
        fmt_hms,
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
    # Consolidate: if panels/system.json exists, render System & Performance Metrics
    if _use_panels_json():
        pj_sys = _read_panel_json("system")
        if isinstance(pj_sys, (dict, list)):
            try:
                from rich.table import Table as RTable
                rtbl = RTable(box=box.SIMPLE_HEAD)
                rtbl.add_column("Category", style="bold")
                rtbl.add_column("Metric")
                rtbl.add_column("Value")
                rtbl.add_column("Status")
                # Compute recent backoff badge (yellow dot) if a WARN backoff_ms within window
                backoff_badge = ""
                try:
                    from datetime import datetime
                    try:
                        window_ms: float = float(load_summary_env().backoff_badge_window_ms)
                    except Exception:
                        window_ms = 120000.0
                    now = datetime.now(UTC)
                    def _ts_in_window(ts: Any) -> bool:
                        if ts is None:
                            return False
                        try:
                            if isinstance(ts, (int, float)):
                                dt2 = datetime.fromtimestamp(float(ts), tz=UTC)
                            else:
                                # try ISO string
                                from scripts.summary.derive import parse_iso as _parse_iso
                                parsed = _parse_iso(ts)
                                if parsed is None:
                                    return False
                                dt2 = parsed
                            delta_ms = (now - dt2).total_seconds() * 1000.0
                            return bool(0 <= delta_ms <= window_ms)
                        except Exception:
                            return False
                    # pj_sys may be dict of categories or list of rows
                    if isinstance(pj_sys, dict):
                        b = pj_sys.get("bridge")
                        if isinstance(b, dict):
                            st = str(b.get("status", "")).upper()
                            met = str(b.get("metric", ""))
                            if st in ("WARN", "WARNING") and met == "backoff_ms" and _ts_in_window(b.get("time")):
                                backoff_badge = " [yellow]● backoff[/]"
                    elif isinstance(pj_sys, list):
                        for it in pj_sys:
                            if isinstance(it, dict):
                                st = str(it.get("status", it.get("state", ""))).upper()
                                met = str(it.get("metric", ""))
                                if st in ("WARN", "WARNING") and met == "backoff_ms" and _ts_in_window(it.get("time")):
                                    backoff_badge = " [yellow]● backoff[/]"
                                    break
                except Exception:
                    backoff_badge = ""
                rows_added = 0
                if isinstance(pj_sys, dict):
                    for k, v in pj_sys.items():
                        if isinstance(v, dict):
                            metric = str(v.get("metric", ""))
                            val = str(v.get("value", v.get("val", "")))
                            st = str(v.get("status", v.get("state", "")))
                            rtbl.add_row(clip(str(k)), clip(metric), clip(val), _dot(st))
                        else:
                            rtbl.add_row(clip(str(k)), "", clip(str(v)), "")
                        rows_added += 1
                        if rows_added >= (8 if not compact else 4):
                            break
                elif isinstance(pj_sys, list):
                    for it in pj_sys[: (8 if not compact else 4)]:
                        if isinstance(it, dict):
                            st = str(it.get("status", it.get("state", "")))
                            rtbl.add_row(
                                clip(str(it.get("category", it.get("name", "")))),
                                clip(str(it.get("metric", ""))),
                                clip(str(it.get("value", it.get("val", "")))),
                                _dot(st),
                            )
                        else:
                            rtbl.add_row("", "", clip(str(it)), "")
                # Append Provider & Resources content as rows (no duplicate header lines)
                # Provider
                prov: dict[str, Any] = {}
                if _use_panels_json():
                    pj_prov = _read_panel_json("provider")
                    if isinstance(pj_prov, dict):
                        prov = pj_prov
                if not prov and status and isinstance(status, dict):
                    p = status.get("provider")
                    if isinstance(p, dict):
                        prov = p
                if prov:
                    # Section header for Provider (only once)
                    rtbl.add_section()
                    name = prov.get("name") or prov.get("provider")
                    if name:
                        rtbl.add_row("", "Name", clip(str(name)), _dot("OK"))
                    auth = prov.get("auth")
                    valid = None
                    if isinstance(auth, dict):
                        valid = auth.get("valid")
                    elif isinstance(auth, bool):
                        valid = auth
                    st = "OK" if valid is True else ("ERROR" if valid is False else "")
                    if valid is not None:
                        rtbl.add_row("", "Auth", ("VALID" if valid else "INVALID"), _dot(st))
                    if prov.get("expiry"):
                        short = fmt_hms(prov["expiry"]) or str(prov["expiry"]).split(".")[0]
                        rtbl.add_row("", "Token Expiry", clip(short), _dot("OK"))
                    if prov.get("latency_ms") is not None:
                        try:
                            env_cfg = load_summary_env()
                            warn_ms = env_cfg.provider_latency_warn_ms
                            err_ms = env_cfg.provider_latency_err_ms
                        except Exception:
                            warn_ms, err_ms = 400.0, 800.0
                        try:
                            lat = float(prov["latency_ms"])  # prov ensured dict above
                            if lat >= err_ms:
                                lat_text = f"[red]{lat:.0f} ms[/]"
                            elif lat >= warn_ms:
                                lat_text = f"[yellow]{lat:.0f} ms[/]"
                            else:
                                lat_text = f"[green]{lat:.0f} ms[/]"
                        except Exception:
                            lat_text = clip(f"{prov['latency_ms']} ms")
                        rtbl.add_row("", "Latency", clip(lat_text), _dot("OK"))
                # Resources
                res: dict[str, Any] = {}
                if _use_panels_json():
                    pj_res = _read_panel_json("resources")
                    if isinstance(pj_res, dict):
                        res = pj_res
                if not res:
                    if status and isinstance(status.get("resources"), dict):
                        res = status["resources"]
                    else:
                        res = collect_resources()
                if res:
                    # Section header for Resources (only once)
                    rtbl.add_section()
                cpu = res.get("cpu")
                if cpu is None and status:
                    cpu = status.get("cpu_pct")
                if isinstance(cpu, (int, float)):
                    rtbl.add_row("", "CPU Usage", clip(f"{cpu:.1f}%"), _dot("OK"))
                rss = res.get("rss")
                if rss is None and status:
                    mem_mb = status.get("memory_mb")
                    if isinstance(mem_mb, (int, float)):
                        rss = float(mem_mb) * 1024 * 1024
                if isinstance(rss, (int, float)):
                    gb = rss / (1024**3)
                    rtbl.add_row("", "Memory RSS", clip(f"{gb:.2f} GB"), _dot("OK"))
                # Footer strip
                footer = Table.grid()
                parts: list[str] = []
                up = None
                if status:
                    up = status.get("uptime_sec") or status.get("uptime")
                if isinstance(up, (int, float)):
                    parts.append(f"Uptime: {fmt_timedelta_secs(float(up))}")
                colls = None
                if status:
                    loop = status.get("loop") if isinstance(status, dict) else None
                    if isinstance(loop, dict):
                        colls = loop.get("count") or loop.get("iterations")
                    if not colls:
                        colls = status.get("collections")
                if isinstance(colls, (int, float)):
                    parts.append(f"Collections: {int(colls)}")
                if parts:
                    footer.add_row("[dim]" + clip(" | ".join(parts)) + "[/dim]")
                    return Panel(
                        Group(rtbl, footer),
                        title=(f"⚡ System & Performance Metrics{backoff_badge}" if show_title else None),
                        border_style=("white" if low_contrast else "green"),
                        expand=True,
                    )
                return Panel(
                    rtbl,
                    title=(f"⚡ System & Performance Metrics{backoff_badge}" if show_title else None),
                    border_style=("white" if low_contrast else "green"),
                    expand=True,
                )
            except Exception:
                pass
    # Default Health panel
    healthy, total, items = derive_health(status)
    # Allow overlay from panels/health.json
    if _use_panels_json():
        pj = _read_panel_json("health")
        if isinstance(pj, dict):
            its: list[tuple[str, str]] = []
            for k, v in pj.items():
                if isinstance(v, dict):
                    its.append((str(k), str(v.get("status", v))))
                else:
                    its.append((str(k), str(v)))
            if its:
                items = its
                healthy = sum(1 for _, s in items if s.lower() in ("ok", "healthy", "ready"))
                total = len(items)
    tbl = Table.grid()
    tbl.add_row(clip(f"Overall: {healthy}/{total} healthy"))
    limit = 3 if compact else 6
    for name, st in items[:limit]:
        tbl.add_row(clip(f"• {name}: {st}"))
    if len(items) > limit:
        tbl.add_row(clip(f"… and {len(items)-limit} more"))
    if low_contrast:
        style = "white"
    else:
        style = "green" if healthy == total and total > 0 else "red"
    return Panel(tbl, title=("Health" if show_title else None), border_style=style, expand=True)
