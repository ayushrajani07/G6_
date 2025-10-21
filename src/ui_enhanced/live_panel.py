"""Placeholder enhanced live panel builder.
Provides richer formatting if enabled, otherwise falls back gracefully.
This is intentionally lightweight until full implementation is supplied.
"""
from __future__ import annotations

from typing import Any

from .color import colorize, status_color

BOX_TOP = "+" + "-"*78 + "+"
BOX_BOTTOM = BOX_TOP

def build_live_panel(*, cycle: int, cycle_time: float, success_rate: float | None,
                     options_processed: int, per_min: float | None, api_success: float | None,
                     api_latency_ms: float | None, memory_mb: float | None, cpu_pct: float | None,
                     indices: dict[str, dict[str, Any]] | None = None, concise: bool = True,
                     market_data: dict[str, Any] | None = None, system_alerts: list[str] | None = None) -> str:
    def fmt(v):
        if v is None: return 'NA'
        if isinstance(v, float): return f"{v:.2f}"
        return str(v)
    status_col, status_bold = status_color('healthy' if (success_rate or 0) >= 95 else 'warn' if (success_rate or 0) >= 80 else 'error')
    header = colorize(f" G6 Cycle {cycle} ", status_col, bold=status_bold)
    lines = [BOX_TOP, f"|{header:<78}|"]
    lines.append(f"| CycleTime: {fmt(cycle_time)}s  Success: {fmt(success_rate)}%  Options: {options_processed}  Rate/min: {fmt(per_min)}{' '*(8)}|")
    lines.append(f"| API Success: {fmt(api_success)}%  Latency: {fmt(api_latency_ms)}ms  CPU: {fmt(cpu_pct)}%  Mem: {fmt(memory_mb)}MB{' '*(4)}|")
    if indices:
        for name, data in indices.items():
            opt = data.get('options')
            atm = data.get('atm')
            lines.append(f"| {name:<10} opt={fmt(opt):<6} atm={fmt(atm):<8} status={data.get('status','?'):<10}{' '*(27)}|")
    if system_alerts:
        for a in system_alerts[:3]:
            lines.append(f"| ALERT: {a[:68]:<68}|")
    lines.append(BOX_BOTTOM)
    return '\n'.join(lines)

__all__ = ['build_live_panel']
