#!/usr/bin/env python3
"""Live cycle panel rendering.

Activated via env G6_LIVE_PANEL=1/true/on. Assumes minimal console formatter.
Call build_live_panel with recent cycle stats; returns multiline string.

We keep it lightweight: pure string ops + color codes.
"""
from __future__ import annotations

import os
import sys
import time
from typing import Any

from src.utils.color import FG_GREEN, FG_MAGENTA, FG_RED, FG_YELLOW, colorize

BORDER_H = "─"
BORDER_V = "│"
BORDER_TL = "┌"
BORDER_TR = "┐"
BORDER_BL = "└"
BORDER_BR = "┘"

_ASCII_FALLBACK = {"─": "-", "│": "|", "┌": "+", "┐": "+", "└": "+", "┘": "+"}
def _needs_ascii_fallback() -> bool:
    if os.environ.get("G6_FORCE_UNICODE", "").lower() in ("1","true","yes","on"):
        return False
    # G6_FORCE_ASCII may be injected from config.console.force_ascii by bootstrap
    if os.environ.get("G6_FORCE_ASCII", "").lower() in ("1","true","yes","on"):
        return True
    enc = getattr(sys.stdout, 'encoding', '') or ''
    return os.name == 'nt' and enc.lower() not in ('utf-8','utf8','utf_8')

_LAST_RENDER_TS = 0.0

# Simple ANSI strip to compute widths
import re

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s)

def _status_color(success_rate: float | None) -> str:
    if success_rate is None:
        return colorize('NA', FG_MAGENTA, bold=True)
    if success_rate >= 99.9:
        return colorize(f"{success_rate:5.1f}%", FG_GREEN)
    if success_rate >= 90.0:
        return colorize(f"{success_rate:5.1f}%", FG_YELLOW)
    return colorize(f"{success_rate:5.1f}%", FG_RED, bold=True)

def _cycle_time_color(cycle_time: float) -> str:
    if cycle_time <= 1.0:
        return colorize(f"{cycle_time:5.2f}s", FG_GREEN)
    if cycle_time <= 3.0:
        return colorize(f"{cycle_time:5.2f}s", FG_YELLOW)
    return colorize(f"{cycle_time:5.2f}s", FG_RED, bold=True)

def _throughput_color(per_min: float | None) -> str:
    if per_min is None:
        return colorize('  NA ', FG_MAGENTA, bold=True)
    if per_min >= 8000:
        return colorize(f"{int(per_min):5d}/m", FG_GREEN)
    if per_min >= 3000:
        return colorize(f"{int(per_min):5d}/m", FG_YELLOW)
    return colorize(f"{int(per_min):5d}/m", FG_RED, bold=True)

def build_live_panel(*, cycle: int, cycle_time: float, success_rate: float | None,
                     options_processed: int, per_min: float | None,
                     api_success: float | None, api_latency_ms: float | None,
                     memory_mb: float | None, cpu_pct: float | None,
                     indices: dict[str, dict[str, Any]] | None = None,
                     concise: bool = True) -> str:
    global _LAST_RENDER_TS
    _LAST_RENDER_TS = time.time()

    # Compose lines
    line1 = f"Cycle {cycle}  Time {_cycle_time_color(cycle_time)}  Success {_status_color(success_rate)}"
    line2 = f"Options {options_processed:5d}  Thru {_throughput_color(per_min)}"
    if api_success is not None:
        if api_success >= 99.5:
            api_s = colorize(f"API {api_success:5.1f}%", FG_GREEN)
        elif api_success >= 90:
            api_s = colorize(f"API {api_success:5.1f}%", FG_YELLOW)
        else:
            api_s = colorize(f"API {api_success:5.1f}%", FG_RED, bold=True)
    else:
        api_s = colorize("API  NA  ", FG_MAGENTA, bold=True)
    if api_latency_ms is not None:
        if api_latency_ms <= 25:
            api_l = colorize(f"{api_latency_ms:4.0f}ms", FG_GREEN)
        elif api_latency_ms <= 80:
            api_l = colorize(f"{api_latency_ms:4.0f}ms", FG_YELLOW)
        else:
            api_l = colorize(f"{api_latency_ms:4.0f}ms", FG_RED, bold=True)
    else:
        api_l = colorize("  NA ", FG_MAGENTA, bold=True)
    if memory_mb is not None:
        if memory_mb < 400:
            mem_s = colorize(f"{memory_mb:5.0f}MB", FG_GREEN)
        elif memory_mb < 900:
            mem_s = colorize(f"{memory_mb:5.0f}MB", FG_YELLOW)
        else:
            mem_s = colorize(f"{memory_mb:5.0f}MB", FG_RED, bold=True)
    else:
        mem_s = colorize("  NA  ", FG_MAGENTA, bold=True)
    if cpu_pct is not None:
        if cpu_pct < 40:
            cpu_s = colorize(f"CPU {cpu_pct:4.0f}%", FG_GREEN)
        elif cpu_pct < 75:
            cpu_s = colorize(f"CPU {cpu_pct:4.0f}%", FG_YELLOW)
        else:
            cpu_s = colorize(f"CPU {cpu_pct:4.0f}%", FG_RED, bold=True)
    else:
        cpu_s = colorize("CPU  NA ", FG_MAGENTA, bold=True)
    line3 = f"{api_s} {api_l}  {mem_s} {cpu_s}"

    index_lines = []
    if indices:
        for name, d in indices.items():
            attempts = d.get('attempts')
            failures = d.get('failures')
            opts = d.get('options')
            atm = d.get('atm')
            status_pct = None
            if attempts and attempts > 0:
                status_pct = (attempts - (failures or 0)) / attempts * 100.0
            status_col = _status_color(status_pct)
            atm_disp = f"ATM {atm}" if atm is not None else ''
            index_lines.append(f"{name:<10} {status_col} {opts:5d} {atm_disp}")

    # Width calc
    content_lines = [line1, line2, line3] + index_lines
    width = max(len(strip_ansi(l)) for l in content_lines)
    width = max(width, 60)

    top = BORDER_TL + BORDER_H * (width + 2) + BORDER_TR
    bottom = BORDER_BL + BORDER_H * (width + 2) + BORDER_BR

    def wrap(l: str) -> str:
        raw_len = len(strip_ansi(l))
        if raw_len < width:
            l = l + ' ' * (width - raw_len)
        return f"{BORDER_V} {l} {BORDER_V}"

    out = [top]
    for l in content_lines:
        out.append(wrap(l))
    out.append(bottom)
    panel = '\n'.join(out)
    if _needs_ascii_fallback():
        for k, v in _ASCII_FALLBACK.items():
            panel = panel.replace(k, v)
    return panel

__all__ = ['build_live_panel']
