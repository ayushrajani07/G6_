from __future__ import annotations
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30))

# Optional psutil
try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

# ---------- Formatting helpers ----------

def fmt_hms_from_dt(dt: datetime) -> str:
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


def clip(text: Any, max_len: Optional[int] = None) -> str:
    s = str(text)
    if max_len is None:
        try:
            from .env import _env_clip_len
            max_len = _env_clip_len()
        except Exception:
            max_len = 60
    if len(s) <= int(max_len):
        return s
    return s[: int(max_len) - 1] + "…"


def parse_iso(ts: Any) -> Optional[datetime]:
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
    except Exception:
        return None
    return None

# ---------- Market hours (IST) ----------

def ist_now() -> datetime:
    return datetime.now(IST_TZ)


def is_market_hours_ist(dt: Optional[datetime] = None) -> bool:
    d = dt or ist_now()
    if d.weekday() >= 5:
        return False
    hm = d.hour * 60 + d.minute
    start = 9 * 60 + 15
    end = 15 * 60 + 30
    return start <= hm <= end


def next_market_open_ist(dt: Optional[datetime] = None) -> Optional[datetime]:
    d = dt or ist_now()
    if is_market_hours_ist(d):
        return None
    candidate = d
    while True:
        candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
        if candidate.weekday() < 5:
            return candidate


# ---------- Derivers ----------

def derive_indices(status: Dict[str, Any] | None) -> List[str]:
    if not status:
        return []
    indices = status.get("indices") or status.get("symbols") or []
    if isinstance(indices, str):
        return [s.strip() for s in indices.split(",") if s.strip()]
    if isinstance(indices, list):
        return [str(s) for s in indices]
    if isinstance(indices, dict):
        return [str(k) for k in indices.keys()]
    return []


def derive_market_summary(status: Dict[str, Any] | None) -> Tuple[str, str]:
    if not status:
        return ("unknown", "next open: —")
    open_flag = status.get("market_open") or status.get("equity_market_open")
    if not open_flag and isinstance(status.get("market"), dict):
        st = str(status["market"].get("status", "")).upper()
        if st:
            open_flag = st == "OPEN"
    next_open = status.get("next_market_open")
    state = "OPEN" if open_flag else "CLOSED"
    extra = ""
    if next_open:
        try:
            if isinstance(next_open, (int, float)):
                dt = datetime.fromtimestamp(float(next_open), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(next_open).replace("Z", "+00:00"))
            delta = (dt - datetime.now(timezone.utc)).total_seconds()
            extra = f"next open: {dt.isoformat().replace('+00:00','Z')} (in {fmt_timedelta_secs(delta)})"
        except Exception:
            try:
                dt = parse_iso(next_open)
                if dt:
                    delta = (dt - datetime.now(timezone.utc)).total_seconds()
                    extra = f"next open: {dt.isoformat().replace('+00:00','Z')} (in {fmt_timedelta_secs(delta)})"
            except Exception:
                extra = f"next open: {next_open}"
    return (state, extra)


def derive_cycle(status: Dict[str, Any] | None) -> Dict[str, Any]:
    d: Dict[str, Any] = {"cycle": None, "last_start": None, "last_duration": None, "success_rate": None}
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
    loop = status.get("loop") if status else None
    if isinstance(loop, dict):
        d["cycle"] = d["cycle"] or loop.get("cycle") or loop.get("number")
        d["last_start"] = d["last_start"] or loop.get("last_run") or loop.get("last_start")
        d["last_duration"] = d["last_duration"] or loop.get("last_duration")
    d["last_start"] = d["last_start"] or status.get("last_cycle_start")
    d["last_duration"] = d["last_duration"] or status.get("last_cycle_duration")
    return d


def estimate_next_run(status: Dict[str, Any] | None, interval: Optional[float]) -> Optional[float]:
    if not status or not interval:
        return None
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
