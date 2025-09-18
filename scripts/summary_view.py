from __future__ import annotations
# pyright: reportGeneralTypeIssues=false, reportUnknownMemberType=false, reportMissingImports=false

import argparse
import json
import os
import sys
import time
import re
from dataclasses import dataclass

# When executed as a script (python scripts/summary_view.py), ensure the project root is on sys.path
try:
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_root = os.path.dirname(_this_dir)
    if _proj_root and _proj_root not in sys.path:
        sys.path.insert(0, _proj_root)
except Exception:
    pass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    # Fallback to fixed offset if zoneinfo unavailable
    IST_TZ = timezone(timedelta(hours=5, minutes=30))
    
# Optional psutil for local resource collection helpers that still reference it
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

# Import sizing helpers now provided by modular env
try:
    from scripts.summary.env import effective_panel_width, panel_height, _env_true, _env_min_col_width  # type: ignore
except Exception:
    # Fallback stubs if env module not available
    def effective_panel_width(name: str) -> Optional[int]:
        return None
    def panel_height(name: str) -> Optional[int]:
        return None
    def _env_true(name: str) -> bool:
        return False
    def _env_min_col_width() -> int:
        return 30

def _env_int(name: str, default: Optional[int] = None) -> Optional[int]:
    try:
        v = os.getenv(name)
        if v is None or v.strip() == "":
            return default
        return int(v)
    except Exception:
        return default

# Minimal output helper used by modular app
def _get_output_lazy():
    class _O:
        def info(self, msg: str, **kw: Any) -> None:
            try:
                print(msg)
            except Exception:
                pass
        def error(self, msg: str, **kw: Any) -> None:
            try:
                print(msg, file=sys.stderr)
            except Exception:
                pass
    return _O()
def fmt_hms_from_dt(dt: datetime) -> str:
    # Format as HH:MM:SS in IST
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST_TZ).strftime("%H:%M:%S")


def fmt_hms(ts: Any) -> Optional[str]:
    if isinstance(ts, datetime):
        return fmt_hms_from_dt(ts)
    if isinstance(ts, (int, float)):
        try:
            return fmt_hms_from_dt(datetime.fromtimestamp(float(ts), tz=timezone.utc))
        except Exception:
            return None
    if isinstance(ts, str):
        dt = parse_iso(ts)
        return fmt_hms_from_dt(dt) if dt else None
    return None


def _env_clip_len() -> int:
    try:
        return max(10, int(os.getenv("G6_PANEL_CLIP", "60")))
    except Exception:
        return 60


def clip(text: Any, max_len: Optional[int] = None) -> str:
    s = str(text)
    if max_len is None:
        max_len = _env_clip_len()
    if len(s) <= int(max_len):
        return s
    # Use single-character ellipsis to keep within max_len
    return s[: int(max_len) - 1] + "…"


def _env_true(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _env_min_col_width() -> int:
    # Minimum width for a column when splitting rows into columns.
    # Defaults to a compact but readable size derived from clip length.
    v = _env_int("G6_PANEL_MIN_COL_W")
    if v and v > 0:
        return v
    return max(30, min(_env_clip_len() + 4, 80))


# ---- Trading hours helpers (IST) ----
def ist_now() -> datetime:
    return datetime.now(IST_TZ)


def is_market_hours_ist(dt: Optional[datetime] = None) -> bool:
    """Return True if now (IST) is within regular trading hours Mon-Fri 09:15–15:30.

    Simple approximation; ignores holidays.
    """
    d = dt or ist_now()
    # Monday=0 .. Sunday=6
    if d.weekday() >= 5:
        return False
    hm = d.hour * 60 + d.minute
    start = 9 * 60 + 15
    end = 15 * 60 + 30
    return start <= hm <= end


def next_market_open_ist(dt: Optional[datetime] = None) -> Optional[datetime]:
    d = dt or ist_now()
    # If within hours, return None
    if is_market_hours_ist(d):
        return None
    # Move to next weekday at 09:15
    candidate = d
    while True:
        candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
        if candidate.weekday() < 5:
            return candidate


@dataclass
class StatusCache:
    path: str
    last_mtime: float = 0.0
    payload: Dict[str, Any] | None = None

    def refresh(self) -> Dict[str, Any] | None:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self.payload = None
            return None
        if st.st_mtime <= self.last_mtime and self.payload is not None:
            return self.payload
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.payload = json.load(f)
            self.last_mtime = st.st_mtime
        except Exception:
            # Do not crash on partial writes
            return self.payload
        return self.payload


def fmt_timedelta_secs(secs: Optional[float]) -> str:
    if secs is None:
        return "—"
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{secs:.1f}s"
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"


def parse_iso(ts: Any) -> Optional[datetime]:
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            # Normalize naive datetimes to UTC-aware
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        return None
    return None


def derive_market_summary(status: Dict[str, Any] | None) -> Tuple[str, str]:
    if not status:
        return ("unknown", "next open: —")
    # Heuristics based on expected fields
    open_flag = status.get("market_open") or status.get("equity_market_open")
    # Support enriched schema: { "market": { "status": "OPEN"|"CLOSED" } }
    if not open_flag and isinstance(status.get("market"), dict):
        st = str(status["market"].get("status", "")).upper()
        if st:
            open_flag = st == "OPEN"
    next_open = status.get("next_market_open")
    state = "OPEN" if open_flag else "CLOSED"
    extra = ""
    if next_open:
        try:
            # Accept either ISO or epoch
            if isinstance(next_open, (int, float)):
                dt = datetime.fromtimestamp(float(next_open), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(next_open).replace("Z", "+00:00"))
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            extra = f"next open: {dt.isoformat().replace('+00:00','Z')} (in {fmt_timedelta_secs(delta)})"
        except Exception:
            extra = f"next open: {next_open}"
    return (state, extra or "")


def _estimate_lines_market(status: Dict[str, Any] | None, interval: Optional[float]) -> int:
    state, extra = derive_market_summary(status)
    lines = 1 + (1 if interval else 0) + (1 if extra else 0)
    return max(1, lines)


def _estimate_lines_loop(status: Dict[str, Any] | None, rolling: Optional[Dict[str, Any]], interval: Optional[float]) -> int:
    cy = derive_cycle(status)
    lines = 1  # cycle
    if cy.get("last_start"):
        lines += 1
    if cy.get("last_duration") is not None:
        lines += 1
    if cy.get("success_rate") is not None:
        lines += 1
    if rolling and (rolling.get("avg") is not None or rolling.get("p95") is not None):
        lines += (1 if rolling.get("avg") is not None else 0) + (1 if rolling.get("p95") is not None else 0)
    if interval and estimate_next_run(status, interval) is not None:
        lines += 1
    return max(1, lines)


def _estimate_lines_health(status: Dict[str, Any] | None, compact: bool) -> int:
    _, _, items = derive_health(status)
    limit = 3 if compact else 6
    return 1 + min(len(items), limit)


def _estimate_lines_sinks(status: Dict[str, Any] | None) -> int:
    sinks = status.get("sinks", {}) if status else {}
    n = 0
    if isinstance(sinks, dict):
        n = min(4, len(sinks))
    # +1 for configured line
    return 1 + n


def _estimate_lines_provider(status: Dict[str, Any] | None) -> int:
    p = derive_provider(status)
    lines = 1  # provider name
    if p.get("auth") is not None:
        lines += 1
    if p.get("expiry"):
        lines += 1
    if p.get("latency_ms") is not None:
        lines += 1
    return lines


def _estimate_lines_resources(status: Dict[str, Any] | None) -> int:
    # CPU + Memory
    return 2


def _estimate_lines_analytics(status: Dict[str, Any] | None, compact: bool) -> int:
    data = (status or {}).get("analytics") if status else None
    if not isinstance(data, dict):
        return 1  # placeholder row
    count = 0
    # Prefer per-index dict
    for _, vals in data.items():
        if isinstance(vals, dict):
            count += 1
    if count == 0:
        # Fall back to global metrics
        if "max_pain" in data and isinstance(data["max_pain"], dict):
            count = len(data["max_pain"])  # may be large, will be limited in panel
        elif "pcr" in data:
            count = 1
    limit = 3 if compact else 6
    return 1 + min(count, limit)  # header + rows


def _estimate_lines_alerts(status: Dict[str, Any] | None, compact: bool) -> int:
    alerts = []
    if status:
        alerts = status.get("alerts") or status.get("events") or []
    count = len(alerts) if isinstance(alerts, list) else 0
    limit = 1 if compact else 3
    return 1 + min(count, limit)  # header + rows


def _estimate_lines_links(metrics_url: Optional[str]) -> int:
    # Status file always shown; metrics optional
    return 1 + (1 if metrics_url else 0)


def derive_indices(status: Dict[str, Any] | None) -> List[str]:
    if not status:
        return []
    indices = status.get("indices") or status.get("symbols") or []
    if isinstance(indices, str):
        # e.g. "NIFTY, BANKNIFTY"
        return [s.strip() for s in indices.split(",") if s.strip()]
    if isinstance(indices, list):
        return [str(s) for s in indices]
    if isinstance(indices, dict):
        return [str(k) for k in indices.keys()]
    return []


# ---- Optional per-panel JSON source (preferred over status when enabled) ----
def _use_panels_json() -> bool:
    # Default ON: prefer data/panels/*.json when available; can disable with env=false
    v = os.getenv("G6_SUMMARY_READ_PANELS")
    if v is None:
        return True
    return _env_true("G6_SUMMARY_READ_PANELS")


def _panels_dir() -> str:
    return os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))


def _read_panel_json(name: str) -> Optional[Any]:
    if not _use_panels_json():
        return None
    path = os.path.join(_panels_dir(), f"{name}.json")
    try:
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            obj = json.load(f)
        # Some writers may wrap data under {"panel": name, "data": {...}}
        if isinstance(obj, dict) and "data" in obj:
            data = obj.get("data")
            return data
        return obj
    except Exception:
        # Ignore partial writes or parse errors
        return None


def _tail_read(path: str, max_bytes: int = 65536) -> Optional[str]:
    try:
        sz = os.path.getsize(path)
        with open(path, "rb") as f:
            if sz > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return data.decode("latin-1", errors="ignore")
    except Exception:
        return None


def _parse_indices_metrics_from_text(text: str) -> Dict[str, Dict[str, Any]]:
    """Parse terminal-style summary lines like:
    "NIFTY TOTAL LEGS: 272 | FAILS: 0 | STATUS: OK"
    Returns { index: {legs:int, fails:int, status:str} }
    """
    out: Dict[str, Dict[str, Any]] = {}
    if not text:
        return out
    # Be generous with whitespace
    pat = re.compile(r"(?P<idx>[A-Z]{3,10})\s+TOTAL\s+LEGS:\s+(?P<legs>\d+)\s*\|\s*FAILS:\s+(?P<fails>\d+)\s*\|\s*STATUS:\s*(?P<status>[A-Z_]+)")
    for m in pat.finditer(text):
        idx = m.group("idx").strip().upper()
        try:
            legs = int(m.group("legs"))
        except Exception:
            legs = None  # type: ignore
        try:
            fails = int(m.group("fails"))
        except Exception:
            fails = None  # type: ignore
        st = m.group("status").strip().upper()
        out[idx] = {"legs": legs, "fails": fails, "status": st}
    return out


def _get_indices_metrics_from_log() -> Dict[str, Dict[str, Any]]:
    # Allow pointing to a file that contains the printed daily options log
    p = os.getenv("G6_INDICES_PANEL_LOG")
    if p and os.path.exists(p):
        txt = _tail_read(p)
        if txt:
            return _parse_indices_metrics_from_text(txt)
    # Weak fallback: try g6_platform.log if present
    if os.path.exists("g6_platform.log"):
        txt = _tail_read("g6_platform.log")
        if txt:
            return _parse_indices_metrics_from_text(txt)
    return {}


def _get_indices_metrics() -> Dict[str, Dict[str, Any]]:
    # Prefer panel JSON when available, then fallback to logs
    if _use_panels_json():
        pj = _read_panel_json("indices")
        if isinstance(pj, dict):
            out: Dict[str, Dict[str, Any]] = {}
            for k, v in pj.items():
                if isinstance(v, dict):
                    out[str(k)] = {**v}
            if out:
                return out
    return _get_indices_metrics_from_log()


def derive_cycle(status: Dict[str, Any] | None) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "cycle": None,
        "last_start": None,
        "last_duration": None,
        "success_rate": None,
    }
    if not status:
        return d
    cycle = status.get("cycle") or status.get("last_cycle")
    if isinstance(cycle, (int, float)):
        d["cycle"] = int(cycle)
    elif isinstance(cycle, dict):
        d["cycle"] = cycle.get("number")
        d["last_start"] = cycle.get("start")
        d["last_duration"] = cycle.get("duration")
        d["success_rate"] = cycle.get("success_rate")
    # Support enriched schema under "loop"
    loop = status.get("loop") if status else None
    if isinstance(loop, dict):
        d["cycle"] = d["cycle"] or loop.get("cycle") or loop.get("number")
        d["last_start"] = d["last_start"] or loop.get("last_run") or loop.get("last_start")
        d["last_duration"] = d["last_duration"] or loop.get("last_duration")
    # Alternate keys
    d["last_start"] = d["last_start"] or status.get("last_cycle_start")
    d["last_duration"] = d["last_duration"] or status.get("last_cycle_duration")
    return d


def estimate_next_run(status: Dict[str, Any] | None, interval: Optional[float]) -> Optional[float]:
    if not status or not interval:
        return None
    # If enriched schema provides a countdown, prefer it
    loop = status.get("loop") if isinstance(status, dict) else None
    if isinstance(loop, dict) and isinstance(loop.get("next_run_in_sec"), (int, float)):
        return max(0.0, float(loop["next_run_in_sec"]))
    last_start = derive_cycle(status).get("last_start")
    if not last_start:
        return None
    dt = parse_iso(last_start)
    if not dt:
        return None
    next_dt = dt.timestamp() + float(interval)
    return max(0.0, next_dt - datetime.now(timezone.utc).timestamp())


def derive_health(status: Dict[str, Any] | None) -> Tuple[int, int, List[Tuple[str, str]]]:
    if not status:
        return (0, 0, [])
    comps = status.get("health") or status.get("components") or {}
    if isinstance(comps, dict):
        items = []
        for k, v in comps.items():
            if isinstance(v, dict):
                val = v.get("status", v)
            else:
                val = v
            items.append((k, str(val)))
        healthy = sum(1 for _, s in items if s.lower() in ("ok", "healthy", "ready"))
        return (healthy, len(items), items)
    if isinstance(comps, list):
        items2 = []
        for c in comps:
            if isinstance(c, dict):
                items2.append((str(c.get("name", "?")), str(c.get("status", "?"))))
        healthy = sum(1 for _, s in items2 if s.lower() in ("ok", "healthy", "ready"))
        return (healthy, len(items2), items2)
    return (0, 0, [])


def derive_provider(status: Dict[str, Any] | None) -> Dict[str, Any]:
    p = {"name": None, "auth": None, "expiry": None, "latency_ms": None}
    if not status:
        return p
    provider = status.get("provider") or status.get("providers")
    if isinstance(provider, dict):
        p["name"] = provider.get("name") or provider.get("primary")
        auth = provider.get("auth") or provider.get("token") or {}
        if isinstance(auth, dict):
            p["auth"] = auth.get("valid")
            p["expiry"] = auth.get("expiry")
        p["latency_ms"] = provider.get("latency_ms")
    return p


def collect_resources() -> Dict[str, Any]:
    out: Dict[str, Any] = {"cpu": None, "rss": None}
    if psutil:
        try:
            out["cpu"] = psutil.cpu_percent(interval=None)
            proc = psutil.Process(os.getpid())
            out["rss"] = proc.memory_info().rss
        except Exception:
            pass
    return out


"""
UI builders previously lived here. The header panel has been moved to scripts.summary.panels.header.
This module now primarily provides:
 - Thin main() wrapper delegating to scripts.summary.app.run
 - StatusCache and plain_fallback helpers
 - Legacy helpers used by tests/panels (may be further reduced later)
"""


def market_panel(status: Dict[str, Any] | None, interval: Optional[float], *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    state, extra = derive_market_summary(status)
    # Overlay from panels/market.json if present
    if _use_panels_json():
        pj = _read_panel_json("market")
        if isinstance(pj, dict):
            st = pj.get("status") or pj.get("state")
            if isinstance(st, str) and st:
                state = st.upper()
            nx = pj.get("next_open")
            if nx is not None:
                try:
                    if isinstance(nx, (int, float)):
                        dt = datetime.fromtimestamp(float(nx), tz=timezone.utc)
                    else:
                        dt = datetime.fromisoformat(str(nx).replace("Z", "+00:00"))
                    delta = (dt - datetime.now(timezone.utc)).total_seconds()
                    extra = f"next open: {dt.isoformat().replace('+00:00','Z')} (in {fmt_timedelta_secs(delta)})"
                except Exception:
                    extra = f"next open: {nx}"
    # Force OPEN during market hours (IST)
    try:
        if is_market_hours_ist():
            state = "OPEN"
            # When open, don't show next_open; otherwise compute a best-effort time
            extra = ""
        else:
            # If closed and we don't have a next open, compute next weekday 09:15 IST
            if not extra:
                nxt = next_market_open_ist()
                if nxt is not None:
                    # Convert IST to UTC ISO for consistency then present
                    nxt_utc = nxt.astimezone(timezone.utc)
                    delta = (nxt_utc - datetime.now(timezone.utc)).total_seconds()
                    extra = f"next open: {nxt_utc.isoformat().replace('+00:00','Z')} (in {fmt_timedelta_secs(delta)})"
    except Exception:
        pass
    tbl = Table.grid()
    tbl.add_row(clip(f"State: [bold]{state}[/]"))
    if interval:
        try:
            tbl.add_row(clip(f"Cycle Interval: {int(float(interval))}s"))
        except Exception:
            tbl.add_row(clip(f"Cycle Interval: {interval}s"))
    if extra:
        tbl.add_row(clip(extra))
    style = "white" if low_contrast else ("green" if state == "OPEN" else "yellow")
    w = effective_panel_width("market")
    return Panel(tbl, title="Market", border_style=style, width=w)


def loop_panel(status: Dict[str, Any] | None, rolling: Optional[Dict[str, Any]] = None, interval: Optional[float] = None, *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    cy = derive_cycle(status)
    if _use_panels_json():
        pj = _read_panel_json("loop")
        if isinstance(pj, dict):
            if pj.get("cycle") is not None:
                cy["cycle"] = pj.get("cycle")
            if pj.get("last_start") is not None:
                cy["last_start"] = pj.get("last_start")
            if pj.get("last_duration") is not None:
                cy["last_duration"] = pj.get("last_duration")
            if pj.get("success_rate") is not None:
                cy["success_rate"] = pj.get("success_rate")
            if rolling is not None:
                if pj.get("avg") is not None:
                    rolling["avg"] = pj.get("avg")
                if pj.get("p95") is not None:
                    rolling["p95"] = pj.get("p95")
    tbl = Table.grid()
    tbl.add_row(clip(f"Cycle: {cy.get('cycle') or '—'}"))
    ls = cy.get("last_start")
    if ls:
        short = fmt_hms(ls)
        tbl.add_row(clip(f"Last start: {short or ls}"))
    ld = cy.get("last_duration")
    if ld is not None:
        tbl.add_row(clip(f"Last duration: {fmt_timedelta_secs(float(ld))}"))
    sr = cy.get("success_rate")
    if sr is not None:
        tbl.add_row(clip(f"Success (rolling): {sr}%"))
    if rolling:
        avg = rolling.get("avg")
        p95 = rolling.get("p95")
        if avg is not None:
            tbl.add_row(clip(f"Avg duration: {fmt_timedelta_secs(float(avg))}"))
        if p95 is not None:
            tbl.add_row(clip(f"P95 duration: {fmt_timedelta_secs(float(p95))}"))
    if interval:
        nr = estimate_next_run(status, interval)
        if nr is not None:
            tbl.add_row(clip(f"Next run in: {fmt_timedelta_secs(nr)}"))
    w = effective_panel_width("loop")
    return Panel(tbl, title="Loop", border_style=("white" if low_contrast else "cyan"), width=w)


def provider_panel(status: Dict[str, Any] | None, *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    p = derive_provider(status)
    if _use_panels_json():
        pj = _read_panel_json("provider")
        if isinstance(pj, dict):
            if pj.get("name") is not None:
                p["name"] = pj.get("name")
            if pj.get("auth") is not None:
                p["auth"] = pj.get("auth")
            if pj.get("expiry") is not None:
                p["expiry"] = pj.get("expiry")
            if pj.get("latency_ms") is not None:
                p["latency_ms"] = pj.get("latency_ms")
    tbl = Table.grid()
    tbl.add_row(clip(f"Provider: {p.get('name') or '—'}"))
    auth = p.get("auth")
    valid = None
    if isinstance(auth, dict):
        valid = auth.get("valid")
    elif isinstance(auth, bool):
        valid = auth
    if valid is True:
        tbl.add_row(clip("Auth: VALID"))
    elif valid is False:
        tbl.add_row(clip("Auth: INVALID"))
    else:
        tbl.add_row(clip("Auth: —"))
    if p.get("expiry"):
        short = fmt_hms(p["expiry"]) or str(p["expiry"])
        tbl.add_row(clip(f"Token expiry: {short}"))
    if p.get("latency_ms") is not None:
        tbl.add_row(clip(f"Latency: {p['latency_ms']} ms"))
    w = effective_panel_width("provider")
    return Panel(tbl, title="Provider", border_style=("white" if low_contrast else "magenta"), width=w)


def health_panel(status: Dict[str, Any] | None, *, low_contrast: bool = False, compact: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich import box  # type: ignore
    from rich.console import Group  # type: ignore
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
                # Attempt a rich table if dict/list of dicts
            try:
                from rich.table import Table as RTable  # type: ignore
                rtbl = RTable(box=box.SIMPLE_HEAD)
                rtbl.add_column("Category", style="bold")
                rtbl.add_column("Metric")
                rtbl.add_column("Value")
                rtbl.add_column("Status")
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
                # Append Provider & Resources content as rows
                # Provider
                prov: Dict[str, Any] = {}
                if _use_panels_json():
                    pj_prov = _read_panel_json("provider")
                    if isinstance(pj_prov, dict):
                        prov = pj_prov
                if not prov and status and isinstance(status, dict):
                    p = status.get("provider")
                    if isinstance(p, dict):
                        prov = p
                if prov:
                    # Section header for Provider
                    rtbl.add_section()
                    rtbl.add_row("", "[dim]— Provider —[/]", "", "")
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
                        rtbl.add_row("", "Latency", clip(f"{prov['latency_ms']} ms"), _dot("OK"))
                # Resources
                res: Dict[str, Any] = {}
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
                    # Section header for Resources
                    rtbl.add_section()
                    rtbl.add_row("", "[dim]— Resources —[/]", "", "")
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
                # Footer strip: uptime and collections if available (no extra banner/header rows)
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
                    return Panel(Group(rtbl, footer), title="⚡ System & Performance Metrics", border_style=("white" if low_contrast else "green"), expand=True)
                return Panel(rtbl, title="⚡ System & Performance Metrics", border_style=("white" if low_contrast else "green"), expand=True)
            except Exception:
                # Fallback to simple grid bullets
                pass
    # Default Health panel
    healthy, total, items = derive_health(status)
    # Allow overlay from panels/health.json
    if _use_panels_json():
        pj = _read_panel_json("health")
        if isinstance(pj, dict):
            its: List[Tuple[str, str]] = []
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
    return Panel(tbl, title="Health", border_style=style, expand=True)


def sinks_panel(status: Dict[str, Any] | None, *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich import box  # type: ignore
    from rich.console import Group  # type: ignore
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
                            # accumulate totals if value seems like size
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
                # Footer summary row
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
                    now_utc = datetime.now(timezone.utc)
                    age = (now_utc - dt).total_seconds()
                    age_str = f" ({fmt_timedelta_secs(age)} ago)"
                    last = fmt_hms_from_dt(dt)
            tbl.add_row(clip(f"• {k}: last write {last or '—'}{age_str}"))
    return Panel(tbl, title="Sinks", border_style=("white" if low_contrast else "cyan"), expand=True)


def config_panel(*, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    defaults = {
        "G6_OUTPUT_SINKS": "stdout,logging",
        "G6_OUTPUT_LEVEL": "info",
    }
    interesting = [
        "G6_MAX_CYCLES",
        "G6_SKIP_PROVIDER_READINESS",
        "G6_FANCY_CONSOLE",
        "G6_FORCE_UNICODE",
        "G6_FORCE_ASCII",
        "G6_OUTPUT_SINKS",
        "G6_OUTPUT_LEVEL",
    ]
    tbl = Table.grid()
    shown = 0
    for k in interesting:
        v = os.getenv(k)
        if v is None:
            continue
        if k in defaults and v == defaults[k]:
            continue
        tbl.add_row(f"{k} = {v}")
        shown += 1
    if shown == 0:
        tbl.add_row("No overrides")
    return Panel(tbl, title="Config", border_style=("white" if low_contrast else "dim"))


def resources_panel(status: Dict[str, Any] | None = None, *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    # Prefer status-provided resources when available
    r: Dict[str, Any] = {}
    if _use_panels_json():
        pj = _read_panel_json("resources")
        if isinstance(pj, dict):
            r = pj
    if not r:
        if status and isinstance(status.get("resources"), dict):
            r = status["resources"]
        else:
            r = collect_resources()
    tbl = Table.grid()
    cpu = r.get("cpu") if isinstance(r, dict) else None
    if cpu is None and status:
        cpu = status.get("cpu_pct")
    rss = r.get("rss") if isinstance(r, dict) else None
    if rss is None and status:
        mem_mb = status.get("memory_mb")
        if isinstance(mem_mb, (int, float)):
            rss = float(mem_mb) * 1024 * 1024
    tbl.add_row(f"CPU: {cpu:.1f}%" if isinstance(cpu, (int, float)) else "CPU: —")
    if isinstance(rss, (int, float)):
        gb = rss / (1024**3)
        tbl.add_row(f"Memory RSS: {gb:.2f} GB")
    else:
        tbl.add_row("Memory RSS: —")
    return Panel(tbl, title="Resources", border_style=("white" if low_contrast else "blue"))


def provider_section(status: Dict[str, Any] | None, *, low_contrast: bool = False) -> Any:
    from rich.table import Table  # type: ignore
    from rich.rule import Rule  # type: ignore
    from rich.console import Group  # type: ignore
    p = {}
    if _use_panels_json():
        pj = _read_panel_json("provider")
        if isinstance(pj, dict):
            p = pj
    if not p and status:
        p = status.get("provider", {}) if isinstance(status, dict) else {}
    tbl = Table.grid()
    name = p.get("name") or p.get("provider") or "provider"
    if name:
        tbl.add_row(clip(f"Provider: {name}"))
    auth = p.get("auth")
    valid = None
    if isinstance(auth, dict):
        valid = auth.get("valid")
    elif isinstance(auth, bool):
        valid = auth
    if valid is True:
        tbl.add_row(clip("Auth: VALID"))
    elif valid is False:
        tbl.add_row(clip("Auth: INVALID"))
    if p.get("expiry"):
        short = fmt_hms(p["expiry"]) or str(p["expiry"]).split(".")[0]
        tbl.add_row(clip(f"Token expiry: {short}"))
    if p.get("latency_ms") is not None:
        tbl.add_row(clip(f"Latency: {p['latency_ms']} ms"))
    return Group(Rule(style=("white" if low_contrast else "dim")), tbl)


def resources_section(status: Dict[str, Any] | None = None, *, low_contrast: bool = False) -> Any:
    from rich.table import Table  # type: ignore
    from rich.rule import Rule  # type: ignore
    from rich.console import Group  # type: ignore
    r: Dict[str, Any] = {}
    if _use_panels_json():
        pj = _read_panel_json("resources")
        if isinstance(pj, dict):
            r = pj
    if not r:
        if status and isinstance(status.get("resources"), dict):
            r = status["resources"]
        else:
            r = collect_resources()
    tbl = Table.grid()
    cpu = r.get("cpu") if isinstance(r, dict) else None
    if cpu is None and status:
        cpu = status.get("cpu_pct")
    rss = r.get("rss") if isinstance(r, dict) else None
    if rss is None and status:
        mem_mb = status.get("memory_mb")
        if isinstance(mem_mb, (int, float)):
            rss = float(mem_mb) * 1024 * 1024
    tbl.add_row(f"CPU: {cpu:.1f}%" if isinstance(cpu, (int, float)) else "CPU: —")
    if isinstance(rss, (int, float)):
        gb = rss / (1024**3)
        tbl.add_row(f"Memory RSS: {gb:.2f} GB")
    else:
        tbl.add_row("Memory RSS: —")
    return Group(Rule(style=("white" if low_contrast else "dim")), tbl)


def indices_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False, loop_for_footer: Optional[Dict[str, Any]] = None) -> Any:
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
        age_str = fmt_timedelta_secs(float(age)) if isinstance(age, (int, float)) else "—"
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


def analytics_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
    from rich import box  # type: ignore
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


def alerts_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    from rich import box  # type: ignore
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
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
    w = effective_panel_width("alerts") or max(40, _env_min_col_width())
    title = f"⚠️ Alerts (E:{nE} W:{nW} I:{nI})" if (nE or nW or nI) else "⚠️ Alerts"
    return Panel(tbl, title=title, border_style=("white" if low_contrast else "red"), width=w)


def links_panel(status_file: str, metrics_url: Optional[str], *, low_contrast: bool = False) -> Any:
    from rich.panel import Panel  # type: ignore
    from rich.table import Table  # type: ignore
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


def build_layout(status: Dict[str, Any] | None, status_file: str, metrics_url: Optional[str], rolling: Optional[Dict[str, Any]] = None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """
    Legacy shim retained temporarily for callers importing from scripts.summary_view.
    Delegates to the modular implementation in scripts.summary.layout.
    """
    from scripts.summary.layout import build_layout as _build_layout  # type: ignore
    return _build_layout(status, status_file, metrics_url, rolling=rolling, compact=compact, low_contrast=low_contrast)


def plain_fallback(status: Dict[str, Any] | None, status_file: str, metrics_url: Optional[str]) -> str:
    indices = ", ".join(derive_indices(status)) or "—"
    market_state, market_extra = derive_market_summary(status)
    cy = derive_cycle(status)
    healthy, total, _ = derive_health(status)
    r = collect_resources()
    lines = [
        f"G6 Unified | IST {fmt_hms_from_dt(datetime.now(timezone.utc))}",
        f"Indices: {indices}",
        f"Market: {market_state} {market_extra}",
        f"Cycle: {cy.get('cycle') or '—'} | Last duration: {fmt_timedelta_secs(cy.get('last_duration'))}",
        f"Health: {healthy}/{total} healthy",
        f"CPU: {r.get('cpu')}% | RSS: {r.get('rss')}",
        f"Status file: {status_file}",
        f"Metrics: {metrics_url or '—'}",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    # Delegate to modular app
    from scripts.summary.app import run as _run
    return _run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
