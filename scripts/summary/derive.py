from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

_FmtFunc = Callable[[Any], str | None]
_fmt_ist_hms_30s: _FmtFunc | None
try:
    from src.utils.timeutils import format_any_to_ist_hms_30s as _imported_fmt
    # Assign with relaxed signature; cast at call sites by runtime check
    _fmt_ist_hms_30s = _imported_fmt  # noqa: F401
except Exception:
    _fmt_ist_hms_30s = None

# Optional psutil
try:
    import psutil  # optional
except Exception:
    psutil = None  # fallback sentinel

# ---------- Formatting helpers ----------

def fmt_hms_from_dt(dt: datetime) -> str:
    if _fmt_ist_hms_30s is not None:
        try:
            s = _fmt_ist_hms_30s(dt)
            if isinstance(s, str):
                return s
        except Exception:
            pass
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M:%S")


def fmt_hms(ts: Any) -> str | None:
    if _fmt_ist_hms_30s is not None:
        try:
            s = _fmt_ist_hms_30s(ts)
            if isinstance(s, str):
                return s
        except Exception:
            pass
    if isinstance(ts, datetime):
        return fmt_hms_from_dt(ts)
    if isinstance(ts, (int, float)):
        try:
            return fmt_hms_from_dt(datetime.fromtimestamp(float(ts), tz=UTC))
        except Exception:
            return None
    if isinstance(ts, str):
        dt = parse_iso(ts)
        return fmt_hms_from_dt(dt) if dt else None
    return None


def fmt_timedelta_secs(secs: float | None) -> str:
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


def clip(text: Any, max_len: int | None = None) -> str:
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


def parse_iso(ts: Any) -> datetime | None:
    try:
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(float(ts), tz=UTC)
        if isinstance(ts, str):
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
    except Exception:
        return None
    return None

# ---------- Market hours (IST) ----------

def ist_now() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


def is_market_hours_ist(dt: datetime | None = None) -> bool:
    d = dt or ist_now()
    if d.weekday() >= 5:
        return False
    hm = d.hour * 60 + d.minute
    start = 9 * 60 + 15
    end = 15 * 60 + 30
    return start <= hm <= end


def next_market_open_ist(dt: datetime | None = None) -> datetime | None:
    d = dt or ist_now()
    if is_market_hours_ist(d):
        return None
    candidate = d
    while True:
        candidate = (candidate + timedelta(days=1)).replace(hour=9, minute=15, second=0, microsecond=0)
        if candidate.weekday() < 5:
            return candidate


# ---------- Derivers ----------

def derive_indices(status: dict[str, Any] | None) -> list[str]:
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


def derive_market_summary(status: dict[str, Any] | None) -> tuple[str, str]:
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
        # Use local variable inside each branch to avoid partially assigned state
        def _fmt_block(dt_val: datetime) -> str:
            delta_local = (dt_val - datetime.now(UTC)).total_seconds()
            from .derive import fmt_hms_from_dt as _fmt
            return f"next open: {_fmt(dt_val)} (in {fmt_timedelta_secs(delta_local)})"
        parsed_dt: datetime | None = None
        try:
            if isinstance(next_open, (int, float)):
                parsed_dt = datetime.fromtimestamp(float(next_open), tz=UTC)
            else:
                parsed_dt = datetime.fromisoformat(str(next_open).replace("Z", "+00:00"))
        except Exception:
            parsed_dt = parse_iso(next_open)
        if parsed_dt is not None:
            try:
                extra = _fmt_block(parsed_dt)
            except Exception:
                extra = f"next open: {next_open}"
        else:
            extra = f"next open: {next_open}"
    return (state, extra)


def derive_cycle(status: dict[str, Any] | None) -> dict[str, Any]:
    d: dict[str, Any] = {"cycle": None, "last_start": None, "last_duration": None, "success_rate": None}
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


def estimate_next_run(status: dict[str, Any] | None, interval: float | None) -> float | None:
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
    return max(0.0, next_dt - datetime.now(UTC).timestamp())


def derive_health(status: dict[str, Any] | None) -> tuple[int, int, list[tuple[str, str]]]:
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
        items2 = [
            (str(c.get("name", "?")), str(c.get("status", "?")))
            for c in comps
            if isinstance(c, dict)
        ]
        healthy = sum(1 for _, s in items2 if s.lower() in ("ok", "healthy", "ready"))
        return (healthy, len(items2), items2)
    return (0, 0, [])


def derive_provider(status: dict[str, Any] | None) -> dict[str, Any]:
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


def collect_resources() -> dict[str, Any]:
    out: dict[str, Any] = {"cpu": None, "rss": None}
    if psutil:
        try:
            out["cpu"] = psutil.cpu_percent(interval=None)
            proc = psutil.Process(os.getpid())
            out["rss"] = proc.memory_info().rss
        except Exception:
            pass
    return out
