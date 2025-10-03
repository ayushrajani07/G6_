"""Placeholder enhanced startup panel builder.
Shows a simple multi-line panel with optional component statuses.
Full animated / progress version can replace this later.
"""
from __future__ import annotations
from typing import Dict, Any
from .color import colorize, FG_GREEN, FG_YELLOW, FG_RED, FG_CYAN, status_color
import datetime
try:
    from src.utils.timeutils import format_ist_dt_30s  # type: ignore
except Exception:  # pragma: no cover
    format_ist_dt_30s = lambda d: d.strftime('%Y-%m-%d %H:%M:%S')  # type: ignore

BORDER = '=' * 80

_DEF_COMPONENTS = ('providers','metrics','storage','health','analytics')

def build_startup_panel(*, version: str, indices, interval: int, concise: bool,
                        provider_readiness: str, readiness_ok: bool,
                        components: Dict[str, str], checks: Dict[str, str], metrics_meta=None) -> str:
    # Unified IST display (30s rounded) for startup panel
    try:
        # Use timezone-aware current UTC (avoid deprecated utcnow) then format IST
        now = format_ist_dt_30s(datetime.datetime.now(datetime.timezone.utc))
    except Exception:
        # Fallback: use timezone-aware UTC then naive format (rare path)
        # DISPLAY_OK: allowed formatting of aware timestamp for UI only
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S')  # fallback (tz-aware source) DISPLAY_OK
    status_col, status_bold = status_color(provider_readiness)
    header = colorize(f"G6 Startup v{version}", status_col, bold=status_bold)
    lines = [BORDER, header, f"Started: {now}  Interval: {interval}s  Mode: {'concise' if concise else 'verbose'}"]
    lines.append(f"Indices: {', '.join(indices) if indices else 'NONE'}")
    lines.append("Components:")
    for c in _DEF_COMPONENTS:
        st = components.get(c,'NA')
        col, bold = status_color(st)
        lines.append(f"  - {c:<10}: {colorize(st, col, bold=bold)}")
    if checks:
        lines.append("Checks:")
        for k,v in checks.items():
            col, bold = status_color(v)
            lines.append(f"  * {k:<12} {colorize(v,col,bold=bold)}")
    if metrics_meta:
        lines.append(f"Metrics: {metrics_meta.get('host')}:{metrics_meta.get('port')}")
    lines.append(BORDER)
    return '\n'.join(lines)

__all__ = ['build_startup_panel']
