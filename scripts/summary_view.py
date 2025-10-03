from __future__ import annotations
# DEPRECATION NOTICE:
# This module is deprecated in favor of `scripts/summary/app.py` (unified summary application).
# It is retained only as a thin compatibility layer providing:
#   * StatusCache
#   * plain_fallback (used by some tests / plain mode)
#   * Legacy wrapper functions (indices_panel, analytics_panel, alerts_panel, links_panel, build_layout)
# New feature work should target the unified summary under scripts/summary/.* and NOT this file.
try:  # Emit a one-time deprecation warning on first import (non-fatal)
    import warnings as _warnings  # noqa: F401
    _warnings.warn(
        "scripts.summary_view is deprecated; use scripts.summary.app (unified summary). This shim will be removed in a future release.",
        DeprecationWarning,
        stacklevel=2,
    )
except Exception:  # pragma: no cover
    pass
# pyright: reportGeneralTypeIssues=false, reportUnknownMemberType=false, reportMissingImports=false

import argparse
import json
import os
import sys
import time
import re
from dataclasses import dataclass

# Ensure the project root is on sys.path using centralized helper
try:
    from src.utils.path_utils import ensure_sys_path
    ensure_sys_path()
except Exception:
    # Minimal bootstrap fallback if imports fail
    _this_dir = os.path.dirname(os.path.abspath(__file__))
    _proj_root = os.path.dirname(_this_dir)
    if _proj_root and _proj_root not in sys.path:
        sys.path.insert(0, _proj_root)
    from src.utils.path_utils import ensure_sys_path
    ensure_sys_path()
from typing import Any, Dict, List, Optional, Tuple, Protocol, Callable
from datetime import datetime, timezone, timedelta
try:
    # Prefer canonical derive helpers from modular summary package
    from scripts.summary.derive import (
        fmt_hms_from_dt, fmt_hms, fmt_timedelta_secs, parse_iso,
        derive_cycle, derive_health, derive_provider, estimate_next_run,
    )  # noqa: F401
except Exception:  # pragma: no cover
    # Fallback: local minimal implementations retained (de-duplicated below if needed)
    from src.utils.timeutils import format_any_to_ist_hms_30s as _fmt_ist_hms_30s  # type: ignore
    def fmt_hms_from_dt(dt: datetime) -> str:  # type: ignore
        try:
            s = _fmt_ist_hms_30s(dt)
            if isinstance(s, str):
                return s
        except Exception:
            pass
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=5, minutes=30))).strftime("%H:%M:%S")
    def fmt_hms(ts: Any) -> Optional[str]:  # type: ignore
        if isinstance(ts, datetime):
            return fmt_hms_from_dt(ts)
        return None
    def fmt_timedelta_secs(secs: Optional[float]) -> str:  # type: ignore
        if secs is None: return "—"
        if secs < 0: secs = 0
        if secs < 60: return f"{secs:.1f}s"
        m, s = divmod(int(secs), 60); h, m = divmod(m, 60)
        return f"{h}h {m}m {s}s" if h else f"{m}m {s}s"
    def parse_iso(ts: Any) -> Optional[datetime]:  # type: ignore
        try:
            if isinstance(ts, (int,float)):
                return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except Exception:
            return None
        return None
    
# Optional psutil for local resource collection helpers that still reference it
try:
    import psutil  # optional dependency
except Exception:  # pragma: no cover
    psutil = None  # psutil not available

# Centralized metrics adapter (optional)
class _MetricsAdapterLike(Protocol):  # minimal surface used here
    def get_cpu_percent(self) -> Optional[float]: ...
    def get_memory_usage_mb(self) -> Optional[float]: ...

try:
    from src.utils.metrics_adapter import get_metrics_adapter  # runtime import; returns adapter
except Exception:  # pragma: no cover
    get_metrics_adapter = None  # adapter not available

# Import sizing helpers now provided by modular env
try:
    from scripts.summary.env import effective_panel_width, panel_height, _env_true as _env_true_env, _env_min_col_width as _env_min_col_width_env  # runtime import
except Exception:  # pragma: no cover
    effective_panel_width = lambda name: None  # noqa: E731
    panel_height = lambda name: None  # noqa: E731
    _env_true_env = lambda name: False  # noqa: E731
    _env_min_col_width_env = lambda: 30  # noqa: E731

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
    """Local env true helper retained for backward compat; prefers env module version if present."""
    try:
        return bool(_env_true_env(name))  # type: ignore[misc]
    except Exception:
        v = os.getenv(name, "").strip().lower()
        return v in ("1", "true", "yes", "on")


def _env_min_col_width() -> int:
    """Local min col width helper (delegates to env module when available)."""
    try:
        val = _env_min_col_width_env()  # type: ignore[misc]
        if isinstance(val, int) and val > 0:
            return val
    except Exception:
        pass
    v = _env_int("G6_PANEL_MIN_COL_W")
    if v and v > 0:
        return v
    return max(30, min(_env_clip_len() + 4, 80))


# ---- Trading hours helpers (IST) ----
def ist_now() -> datetime:
    try:
        # Prefer system zoneinfo if available
        from zoneinfo import ZoneInfo  # Python 3.9+ stdlib
        return datetime.now(ZoneInfo("Asia/Kolkata"))
    except Exception:
        return datetime.now(timezone(timedelta(hours=5, minutes=30)))


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
        # Use centralized StatusReader for consistent IO; preserve previous
        # behavior: on partial writes or decode errors, keep last payload.
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            self.payload = None
            return None
        if st.st_mtime <= self.last_mtime and self.payload is not None:
            return self.payload
        try:
            from src.utils.status_reader import get_status_reader  # runtime import
        except Exception:
            get_status_reader = None  # type: ignore
        try:
            if get_status_reader is not None:
                reader = get_status_reader(self.path)
                data = reader.get_raw_status()
                if isinstance(data, dict) and (data or self.payload is None):
                    self.payload = data
                    self.last_mtime = st.st_mtime
                    return self.payload
                # If empty dict while we have previous payload, treat as transient
                # and keep last payload unchanged.
                return self.payload
            # Fallback to direct read if reader unavailable
            with open(self.path, "r", encoding="utf-8") as f:
                self.payload = json.load(f)
            self.last_mtime = st.st_mtime
        except Exception:
            # Do not crash on partial writes
            return self.payload
        return self.payload


def derive_market_summary(status: Dict[str, Any] | None) -> Tuple[str, str]:  # backward compat shim
    from scripts.summary.derive import derive_market_summary as _dms  # type: ignore
    return _dms(status)

def _estimate_lines_market(status: Dict[str, Any] | None, interval: Optional[float]) -> int:  # relies on derive module
    from scripts.summary.derive import derive_market_summary as _dms  # type: ignore
    state, extra = _dms(status)
    return max(1, 1 + (1 if interval else 0) + (1 if extra else 0))


def _estimate_lines_loop(status: Dict[str, Any] | None, rolling: Optional[Dict[str, Any]], interval: Optional[float]) -> int:
    from scripts.summary.derive import derive_cycle as _dc, estimate_next_run as _enr  # type: ignore
    cy = _dc(status)
    lines = 1
    if cy.get("last_start"): lines += 1
    if cy.get("last_duration") is not None: lines += 1
    if cy.get("success_rate") is not None: lines += 1
    if rolling and (rolling.get("avg") is not None or rolling.get("p95") is not None):
        lines += (1 if rolling.get("avg") is not None else 0) + (1 if rolling.get("p95") is not None else 0)
    if interval and _enr(status, interval) is not None:
        lines += 1
    return max(1, lines)


def _estimate_lines_health(status: Dict[str, Any] | None, compact: bool) -> int:
    from scripts.summary.derive import derive_health as _dh  # type: ignore
    _, _, items = _dh(status)
    return 1 + min(len(items), 3 if compact else 6)


def _estimate_lines_sinks(status: Dict[str, Any] | None) -> int:
    sinks = status.get("sinks", {}) if status else {}
    n = 0
    if isinstance(sinks, dict):
        n = min(4, len(sinks))
    # +1 for configured line
    return 1 + n


def _estimate_lines_provider(status: Dict[str, Any] | None) -> int:
    from scripts.summary.derive import derive_provider as _dp  # type: ignore
    p = _dp(status)
    lines = 1
    if p.get("auth") is not None: lines += 1
    if p.get("expiry"): lines += 1
    if p.get("latency_ms") is not None: lines += 1
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
    alerts: List[Any] = []
    if status:
        alerts = status.get("alerts") or status.get("events") or []
    count = len(alerts) if isinstance(alerts, list) else 0
    limit = 1 if compact else 3
    return 1 + min(count, limit)  # header + rows


def _estimate_lines_links(metrics_url: Optional[str]) -> int:
    # Status file always shown; metrics optional
    return 1 + (1 if metrics_url else 0)


def derive_indices(status: Dict[str, Any] | None) -> List[str]:
    """Delegate to centralized derive. Kept for backward compatibility."""
    try:
        from scripts.summary.derive import derive_indices as _derive_indices
        return _derive_indices(status)
    except Exception:
        # Fallback to local minimal logic if import fails
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


# ---- Optional per-panel JSON source (preferred over status when enabled) ----
def _use_panels_json() -> bool:
    """Return whether panels JSON artifacts should be used (auto-detect).

    Primary logic delegated to scripts.summary.data_source._use_panels_json. Deprecated
    env vars (G6_SUMMARY_PANELS_MODE / G6_SUMMARY_READ_PANELS) are ignored globally.
    If import fails (rare / minimal environment), fall back to False (status-only) to
    avoid unexpected file IO assumptions in constrained test contexts.
    """
    try:
        from scripts.summary.data_source import _use_panels_json as _use
        return _use()
    except Exception:
        return False


def _panels_dir() -> str:
    return os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))


def _read_json_with_retries(path: str, retries: int = 3, delay: float = 0.05) -> Optional[Any]:
    """Read JSON file with a brief retry loop to mitigate transient partial reads."""
    for attempt in range(max(1, retries)):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            if attempt == retries - 1:
                break
            try:
                import time
                time.sleep(delay)
            except Exception:
                pass
    return None


def _read_panel_json(name: str) -> Optional[Any]:
    """Delegate to centralized data_source._read_panel_json to avoid duplication."""
    try:
        from scripts.summary.data_source import _read_panel_json as _read
        return _read(name)
    except Exception:
        if not _use_panels_json():
            return None
        # Conservative fallback to direct file read
        path = os.path.join(_panels_dir(), f"{name}.json")
        try:
            if not os.path.exists(path):
                return None
            obj = _read_json_with_retries(path)
            return obj if obj is not None else None
        except Exception:
            return None


"""
UI builders previously lived here. The header panel has been moved to scripts.summary.panels.header.
This module now primarily provides:
 - Thin main() wrapper delegating to scripts.summary.app.run
 - StatusCache and plain_fallback helpers
 - Legacy wrappers used by callers (indices_panel, analytics_panel, alerts_panel, links_panel)
"""


def derive_cycle(status: Dict[str, Any] | None) -> Dict[str, Any]:
    """DEPRECATED: Use scripts.summary.derive.derive_cycle.

    This local implementation remains for backward compatibility with
    external imports. It will be removed in a future release once callers
    migrate to the centralized derive module.
    """
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
    """DEPRECATED: Use scripts.summary.derive.estimate_next_run"""
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


_DERIVE_WARNED = {"health": False, "provider": False}

def derive_health(status: Dict[str, Any] | None) -> Tuple[int, int, List[Tuple[str, str]]]:
    """DEPRECATED shim. Use scripts.summary.derive.derive_health instead.

    This wrapper will be removed after downstream callers migrate.
    """
    global _DERIVE_WARNED
    if not _DERIVE_WARNED["health"]:
        import warnings
        warnings.warn("derive_health imported from summary_view is deprecated; use scripts.summary.derive", DeprecationWarning, stacklevel=2)
        _DERIVE_WARNED["health"] = True
    from scripts.summary.derive import derive_health as _h  # lazy import
    return _h(status)


def derive_provider(status: Dict[str, Any] | None) -> Dict[str, Any]:
    """DEPRECATED shim. Use scripts.summary.derive.derive_provider instead."""
    global _DERIVE_WARNED
    if not _DERIVE_WARNED["provider"]:
        import warnings
        warnings.warn("derive_provider imported from summary_view is deprecated; use scripts.summary.derive", DeprecationWarning, stacklevel=2)
        _DERIVE_WARNED["provider"] = True
    from scripts.summary.derive import derive_provider as _p
    return _p(status)


def collect_resources() -> Dict[str, Any]:
    out: Dict[str, Any] = {"cpu": None, "rss": None}
    # Prefer centralized metrics adapter if available
    try:
        if get_metrics_adapter is not None:
            ma = get_metrics_adapter()
            cpu = ma.get_cpu_percent()
            mem_mb = ma.get_memory_usage_mb()
            if isinstance(cpu, (int, float)):
                out["cpu"] = cpu
            if isinstance(mem_mb, (int, float)):
                out["rss"] = int(mem_mb * 1024 * 1024)
    except Exception:
        pass
    if psutil:
        try:
            if out.get("cpu") is None:
                out["cpu"] = psutil.cpu_percent(interval=None)
            if out.get("rss") is None:
                proc = psutil.Process(os.getpid())
                out["rss"] = proc.memory_info().rss
        except Exception:
            pass
    return out


"""
Note: Previously, this module also contained various UI builder helpers (sinks_panel, config_panel, resources_panel, provider_section, resources_section)
and low-level log parsing helpers (_tail_read, _parse_indices_metrics_from_text, _get_indices_metrics).
These have been removed to avoid duplication since the single source of truth lives under scripts.summary.panels.* and scripts.summary.data_source.
"""


def indices_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False, loop_for_footer: Optional[Dict[str, Any]] = None) -> Any:
    """Legacy wrapper delegating to modular indices panel.

    Kept for backward compatibility with imports from scripts.summary_view.
    """
    from scripts.summary.panels.indices import indices_panel as _indices_panel
    return _indices_panel(status, compact=compact, low_contrast=low_contrast, loop_for_footer=loop_for_footer)


def analytics_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """Legacy wrapper delegating to modular analytics panel."""
    from scripts.summary.panels.analytics import analytics_panel as _analytics_panel
    return _analytics_panel(status, compact=compact, low_contrast=low_contrast)


def alerts_panel(status: Dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """Legacy wrapper delegating to modular alerts panel."""
    from scripts.summary.panels.alerts import alerts_panel as _alerts_panel
    return _alerts_panel(status, compact=compact, low_contrast=low_contrast)


def links_panel(status_file: str, metrics_url: Optional[str], *, low_contrast: bool = False) -> Any:
    """Legacy wrapper delegating to modular links panel."""
    from scripts.summary.panels.links import links_panel as _links_panel
    return _links_panel(status_file, metrics_url, low_contrast=low_contrast)


def build_layout(status: Dict[str, Any] | None, status_file: str, metrics_url: Optional[str], rolling: Optional[Dict[str, Any]] = None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """
    Legacy shim retained temporarily for callers importing from scripts.summary_view.
    Delegates to the modular implementation in scripts.summary.layout.
    """
    from scripts.summary.layout import build_layout as _build_layout
    return _build_layout(status, status_file, metrics_url, rolling=rolling, compact=compact, low_contrast=low_contrast)


def plain_fallback(status: Dict[str, Any] | None, status_file: str, metrics_url: Optional[str]) -> str:
    # Unified path: leverage model assembler as single derivation source.
    # Curated layout short-circuit retained. Legacy raw fallbacks reduced to
    # only adaptive/detail lines (provider/resources now always sourced via model).
    # The broad "G6 Unified (fallback)" legacy string is deprecated; retained
    # only as a last-resort safety net (tests no longer rely on it).
    try:
        if 'os' in globals() and os.getenv("G6_SUMMARY_CURATED_MODE", "").strip().lower() in {"1","true","yes","on"}:
            try:
                from src.summary.curated_layout import CuratedLayout, collect_state
                st = collect_state(status)
                renderer = CuratedLayout()
                return renderer.render(st)
            except Exception:
                pass
        # Assemble model snapshot (preferred stable representation)
        from src.summary.unified.model import assemble_model_snapshot
        model, _diag = assemble_model_snapshot(runtime_status=status or {}, panels_dir=os.getenv("G6_PANELS_DIR"), include_panels=True)
        # Build concise lines from model
        indices_names = ", ".join([i.name for i in model.indices]) or "—"
        dq_line = None
        try:
            if (model.dq.green + model.dq.warn + model.dq.error) > 0:
                dq_line = f"DQ: G/Y/R {model.dq.green}/{model.dq.warn}/{model.dq.error} (thr {int(model.dq.warn_threshold)}/{int(model.dq.error_threshold)})"
        except Exception:
            dq_line = None
        # Adaptive alerts summary (stable 'Adaptive alerts:' token for tests)
        adaptive_line = None
        try:
            total_alerts = int(getattr(model.adaptive, 'alerts_total', 0) or 0)
            if total_alerts > 0:
                pairs = []
                try:
                    pairs = sorted(list((model.adaptive.alerts_by_type or {}).items()), key=lambda kv: kv[1], reverse=True)
                except Exception:
                    pairs = []
                top = ", ".join(f"{k}:{v}" for k, v in pairs[:2]) if pairs else ""
                adaptive_line = f"Adaptive alerts: {total_alerts}" + (f" ({top})" if top else "")
                try:
                    sev = model.adaptive.severity_counts or {}
                    c = sev.get('critical') or 0
                    w = sev.get('warn') or 0
                    if c or w:
                        adaptive_line += f" [C:{c} W:{w}]"
                except Exception:
                    pass
        except Exception:
            adaptive_line = None
        # Fallback: derive from raw status 'adaptive_alerts' list if model had none OR model reported zero but raw has items
        if adaptive_line is None or (adaptive_line is None and isinstance(status, dict) and status.get('adaptive_alerts')):
            try:
                raw_alerts: List[Dict[str, Any]] = []
                if isinstance(status, dict):
                    ra = status.get('adaptive_alerts')
                    if isinstance(ra, list):
                        raw_alerts = [a for a in ra if isinstance(a, dict)]
                if raw_alerts:
                    total_alerts = len(raw_alerts)
                    counts: Dict[str,int] = {}
                    for a in raw_alerts:
                        t = a.get('type') if isinstance(a, dict) else None
                        if isinstance(t, str):
                            counts[t] = counts.get(t,0)+1
                    pairs = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                    top = ", ".join(f"{k}:{v}" for k,v in pairs[:2]) if pairs else ""
                    adaptive_line = f"Adaptive alerts: {total_alerts}" + (f" ({top})" if top else "")
            except Exception:
                pass

        # Detail mode line (option detail / adaptive band/agg context) pulled from raw status fallbacks if not in model
        detail_line = None
        try:
            raw = status or {}
            dm = raw.get('option_detail_mode') or raw.get('detail_mode')
            dm_str = raw.get('option_detail_mode_str') or raw.get('detail_mode_str')
            band_win = raw.get('option_detail_band_window') or raw.get('detail_band_window')
            if dm is not None or dm_str or band_win is not None:
                core = f"Detail mode: {dm_str or dm or 'unknown'}"
                if dm_str == 'band' and band_win is not None:
                    # Represent +/- window consistently (tests allow ± or +-)
                    core += f" (±{band_win})"
                elif dm_str and band_win is not None:
                    core += f" ({band_win})"
                detail_line = core
        except Exception:
            detail_line = None
        # Provider & resources always via model; no raw duplication fallback needed
        provider_name = model.provider.get('name') if isinstance(model.provider, dict) else None
        health_line = f"Provider: {provider_name}" if provider_name else None
        cpu = model.resources.get('cpu') if isinstance(model.resources, dict) else None
        rss = model.resources.get('rss') if isinstance(model.resources, dict) else None
        res_line = f"CPU: {cpu}% | RSS: {rss}" if (cpu is not None or rss is not None) else None
        cycle_line = None
        try:
            if model.cycle.number is not None:
                cycle_line = f"Cycle: {model.cycle.number} | Last duration: {model.cycle.last_duration_sec}s"
        except Exception:
            pass
        # Ensure adaptive/detail lines from raw status if still missing
        if adaptive_line is None and isinstance(status, dict):
            try:
                ra = status.get('adaptive_alerts')
                if isinstance(ra, list) and ra:
                    adaptive_line = f"Adaptive alerts: {len(ra)}"
            except Exception:
                pass
        if detail_line is None and isinstance(status, dict):
            try:
                dm = status.get('option_detail_mode') or status.get('detail_mode')
                dm_str = status.get('option_detail_mode_str') or status.get('detail_mode_str')
                band_win = status.get('option_detail_band_window') or status.get('detail_band_window')
                if dm is not None or dm_str or band_win is not None:
                    core = f"Detail mode: {dm_str or dm or 'unknown'}"
                    if (dm_str == 'band' or dm == 1) and band_win is not None:
                        core += f" (±{band_win})"
                    detail_line = core
            except Exception:
                pass
        lines: List[str] = [
            f"G6 Unified | IST {fmt_hms_from_dt(datetime.now(timezone.utc))}",
            f"Indices: {indices_names}",
            *( [dq_line] if dq_line else [] ),
            f"Market: {model.market_status}",
            *( [adaptive_line] if adaptive_line else [] ),
            *( [detail_line] if detail_line else [] ),
            *( [cycle_line] if cycle_line else [] ),
            *( [health_line] if health_line else [] ),
            *( [res_line] if res_line else [] ),
            f"Status file: {status_file}",
            f"Metrics: {metrics_url or '—'}",
        ]
        return "\n".join(lines)
    except Exception:
        # Fall back to legacy behavior if any part fails (safety net)
        try:
            return f"G6 Unified (fallback) | Status file: {status_file}\nMetrics: {metrics_url or '—'}"
        except Exception:
            return "G6 Unified (fallback)"


def main(argv: Optional[List[str]] = None) -> int:
    # Delegate to modular app
    from scripts.summary.app import run as _run
    return _run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
