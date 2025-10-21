from __future__ import annotations

"""DEPRECATED summary_view shim.

This file will be removed after the deprecation window (see DEPRECATIONS.md).
Only retained for:
    * StatusCache
    * plain_fallback
    * Legacy panel wrapper functions (indices_panel, analytics_panel, alerts_panel, links_panel, build_layout)

DO NOT add new functionality here. All new work must target `scripts/summary/app.py`
and related modular packages.

Removal Plan (proposed):
    - R+1: Emit runtime deprecation warning on import (already active)
    - R+2: Convert wrappers to raising ImportError with migration message when env G6_STRICT_DEPRECATIONS=1
    - R+3: Delete file
"""
try:  # Emit a one-time deprecation warning on first import (non-fatal)
    import warnings as _warnings  # noqa: F401
    _warnings.warn(
        "scripts.summary_view is deprecated; use scripts.summary.app (unified summary). Removal planned (see DEPRECATIONS.md).",
        DeprecationWarning,
        stacklevel=2,
    )
except Exception:  # pragma: no cover
    pass
# pyright: reportGeneralTypeIssues=false, reportUnknownMemberType=false, reportMissingImports=false

import json
import os
import sys
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
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Protocol

from scripts.summary.derive import fmt_hms_from_dt  # narrow import; other helpers unused here

# Optional psutil for local resource collection helpers that still reference it
try:
    import psutil  # optional dependency
except Exception:  # pragma: no cover
    psutil = None  # psutil not available

# Centralized metrics adapter (optional)
class _MetricsAdapterLike(Protocol):  # minimal surface used here
    def get_cpu_percent(self) -> float | None: ...
    def get_memory_usage_mb(self) -> float | None: ...

try:
    from src.utils.metrics_adapter import get_metrics_adapter  # runtime import; returns adapter
except Exception:  # pragma: no cover
    get_metrics_adapter = None  # adapter not available

# Import sizing helpers now provided by modular env
try:
    from scripts.summary.env import _env_min_col_width as _env_min_col_width_env
    from scripts.summary.env import _env_true as _env_true_env
    from scripts.summary.env import effective_panel_width, panel_height  # runtime import
except Exception:  # pragma: no cover
    effective_panel_width = lambda name: None  # noqa: E731
    panel_height = lambda name: None  # noqa: E731
    _env_true_env = lambda name: False  # noqa: E731
    _env_min_col_width_env = lambda: 30  # noqa: E731

def _env_int(name: str, default: int | None = None) -> int | None:
    try:
        v = os.getenv(name)
        if v is None or v.strip() == "":
            return default
        return int(v)
    except Exception:
        return default

# Minimal output helper used by modular app
def _get_output_lazy() -> Any:
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


def clip(text: Any, max_len: int | None = None) -> str:
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


def is_market_hours_ist(dt: datetime | None = None) -> bool:
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


def next_market_open_ist(dt: datetime | None = None) -> datetime | None:
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
    payload: dict[str, Any] | None = None

    def refresh(self) -> dict[str, Any] | None:
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
            # Fallback: use cached JSON reader when available, else direct read
            try:
                from pathlib import Path as _Path

                from src.utils.csv_cache import read_json_cached as _read_json_cached
                self.payload = _read_json_cached(_Path(self.path))
            except Exception:
                with open(self.path, encoding="utf-8") as f:
                    self.payload = json.load(f)
            self.last_mtime = st.st_mtime
        except Exception:
            # Do not crash on partial writes
            return self.payload
        return self.payload


def derive_market_summary(status: dict[str, Any] | None) -> tuple[str, str]:  # backward compat shim
    from scripts.summary.derive import derive_market_summary as _dms  # type: ignore
    try:
        res = _dms(status)
        if isinstance(res, tuple) and len(res) == 2 and all(isinstance(x, str) for x in res):
            return res  # type: ignore[return-value]
    except Exception:
        pass
    return ("", "")

## Removed legacy line estimation helpers (migrated to modular panels & layout)


def derive_indices(status: dict[str, Any] | None) -> list[str]:
    """Delegate to centralized derive. Kept for backward compatibility."""
    try:
        from scripts.summary.derive import derive_indices as _derive_indices
        res = _derive_indices(status)
        if isinstance(res, list):
            return [str(x) for x in res]
        return []
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
        return bool(_use())
    except Exception:
        return False


def _panels_dir() -> str:
    return os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))


def _read_json_with_retries(path: str, retries: int = 3, delay: float = 0.05) -> Any | None:
    """Read JSON file with a brief retry loop to mitigate transient partial reads."""
    for attempt in range(max(1, retries)):
        try:
            with open(path, encoding="utf-8") as f:
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


def _read_panel_json(name: str) -> Any | None:
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


## Removed deprecated derive_cycle / estimate_next_run local shims (use scripts.summary.derive instead)


_DERIVE_WARNED = {"health": False, "provider": False}

## Removed derive_health / derive_provider legacy shims (callers must update imports)


def collect_resources() -> dict[str, Any]:
    out: dict[str, Any] = {"cpu": None, "rss": None}
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


def indices_panel(status: dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False, loop_for_footer: dict[str, Any] | None = None) -> Any:
    """Legacy wrapper delegating to modular indices panel.

    Kept for backward compatibility with imports from scripts.summary_view.
    """
    from scripts.summary.panels.indices import indices_panel as _indices_panel
    return _indices_panel(status, compact=compact, low_contrast=low_contrast, loop_for_footer=loop_for_footer)


def analytics_panel(status: dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """Legacy wrapper delegating to modular analytics panel."""
    from scripts.summary.panels.analytics import analytics_panel as _analytics_panel
    return _analytics_panel(status, compact=compact, low_contrast=low_contrast)


def alerts_panel(status: dict[str, Any] | None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """Legacy wrapper delegating to modular alerts panel."""
    from scripts.summary.panels.alerts import alerts_panel as _alerts_panel
    return _alerts_panel(status, compact=compact, low_contrast=low_contrast)


def links_panel(status_file: str, metrics_url: str | None, *, low_contrast: bool = False) -> Any:
    """Legacy wrapper delegating to modular links panel."""
    from scripts.summary.panels.links import links_panel as _links_panel
    return _links_panel(status_file, metrics_url, low_contrast=low_contrast)


def build_layout(status: dict[str, Any] | None, status_file: str, metrics_url: str | None, rolling: dict[str, Any] | None = None, *, compact: bool = False, low_contrast: bool = False) -> Any:
    """
    Legacy shim retained temporarily for callers importing from scripts.summary_view.
    Delegates to the modular implementation in scripts.summary.layout.
    """
    from scripts.summary.layout import build_layout as _build_layout
    return _build_layout(status, status_file, metrics_url, rolling=rolling, compact=compact, low_contrast=low_contrast)


def plain_fallback(status: dict[str, Any] | None, status_file: str, metrics_url: str | None) -> str:
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
                return str(renderer.render(st))
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
                raw_alerts: list[dict[str, Any]] = []
                if isinstance(status, dict):
                    ra = status.get('adaptive_alerts')
                    if isinstance(ra, list):
                        raw_alerts = [a for a in ra if isinstance(a, dict)]
                if raw_alerts:
                    total_alerts = len(raw_alerts)
                    counts: dict[str,int] = {}
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
        lines: list[str] = [
            f"G6 Unified | IST {fmt_hms_from_dt(datetime.now(UTC))}",
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


def main(argv: list[str] | None = None) -> int:
    # Delegate to modular app
    from scripts.summary.app import run as _run
    res = _run(argv)
    try:
        return int(res)
    except Exception:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
