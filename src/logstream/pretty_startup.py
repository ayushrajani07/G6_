#!/usr/bin/env python3
"""Fancy colorful startup panel builder for G6.

Activated when env G6_FANCY_CONSOLE=1/true/on.
Relies on minimal console formatter (message only) so we can output rich
multi-line panels without noisy prefixes.
"""
from __future__ import annotations

import datetime
import os
import sys
from collections.abc import Iterable
from typing import Any

from src.utils.color import FG_GREEN, FG_MAGENTA, FG_RED, FG_YELLOW, colorize

BORDER_H = "═"
BORDER_V = "║"
BORDER_TL = "╔"
BORDER_TR = "╗"
BORDER_BL = "╚"
BORDER_BR = "╝"
SEP = "─"

# Windows legacy code pages (e.g. cp1252) may fail to encode these characters when logs
# are redirected. We provide a conservative ASCII fallback if an encoding error appears.
_ASCII_FALLBACK = {"═": "=", "║": "|", "╔": "+", "╗": "+", "╚": "+", "╝": "+", "─": "-"}
def _needs_ascii_fallback() -> bool:
    if os.environ.get("G6_FORCE_UNICODE", "").lower() in ("1","true","yes","on"):
        return False
    # Allow config-sourced default via injected env by bootstrap (console.force_ascii)
    if os.environ.get("G6_FORCE_ASCII", "").lower() in ("1","true","yes","on"):
        return True
    enc = getattr(sys.stdout, 'encoding', '') or ''
    return os.name == 'nt' and enc.lower() not in ('utf-8','utf8','utf_8')

# Status color map
_STATUS_COLORS = {
    'healthy': (FG_GREEN, True),
    'ok': (FG_GREEN, False),
    'ready': (FG_GREEN, True),
    'degraded': (FG_YELLOW, True),
    'warn': (FG_YELLOW, True),
    'warning': (FG_YELLOW, True),
    'error': (FG_RED, True),
    'unhealthy': (FG_RED, True),
    'fail': (FG_RED, True),
    'critical': (FG_RED, True),
}

def status_token(text: str) -> str:
    t = (text or '').strip().lower()
    color_bold = _STATUS_COLORS.get(t)
    if not color_bold:
        # fallback heuristic
        if 'healthy' in t or 'ready' in t:
            color_bold = (FG_GREEN, True)
        elif 'warn' in t or 'degrade' in t:
            color_bold = (FG_YELLOW, True)
        elif 'fail' in t or 'error' in t or 'unhealthy' in t:
            color_bold = (FG_RED, True)
        else:
            color_bold = (FG_MAGENTA, True)
    col, bold = color_bold
    return colorize(text, col, bold=bold)

def pad(text: str, width: int) -> str:
    ln = len(strip_ansi(text))
    if ln >= width:
        return text
    return text + ' ' * (width - ln)

# Basic ANSI stripper for width calculation
import re

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*m')

def strip_ansi(s: str) -> str:
    return _ANSI_RE.sub('', s)

def build_section(title: str, lines: Iterable[str], inner_width: int) -> list[str]:
    out = []
    title_disp = f" {title.upper()} "
    bar = title_disp + SEP * max(0, inner_width - len(title_disp))
    out.append(colorize(bar, FG_MAGENTA, bold=True))
    for ln in lines:
        out.append(ln)
    return out

def build_startup_panel(*, version: str, indices: Iterable[str], interval: int, concise: bool,
                        provider_readiness: str, readiness_ok: bool,
                        components: dict[str, str], checks: dict[str, str],
                        metrics_meta: dict[str, Any] | None = None) -> str:
    """Return a rich multi-line panel summarizing startup state."""
    indices_list = ', '.join(indices) if indices else 'NONE'
    now_disp = datetime.datetime.now().strftime('%d-%b-%Y %H:%M:%S')  # local-ok

    # Sections
    core_lines = [
        f"Version: {colorize(version, FG_GREEN, bold=True)}",
        f"Indices: {colorize(indices_list, FG_YELLOW, bold=True)}",
        f"Interval: {interval}s  Mode: {'concise' if concise else 'verbose'}",
        f"Started: {now_disp}",
    ]
    prov_line = f"Provider: {status_token(provider_readiness)}"
    core_lines.append(prov_line)

    comp_lines = []
    for name, status in components.items():
        comp_lines.append(f"{name}: {status_token(status)}")
    chk_lines = []
    for name, status in checks.items():
        chk_lines.append(f"{name}: {status_token(status)}")

    metrics_lines: list[str] = []
    if metrics_meta:
        metrics_lines.append(f"Bind: {metrics_meta.get('host')}:{metrics_meta.get('port')}")
        if metrics_meta.get('resource_sampler'):
            metrics_lines.append(status_token('sampler'))
        if metrics_meta.get('watchdog'):
            metrics_lines.append(status_token('watchdog'))
        if metrics_meta.get('custom_registry'):
            metrics_lines.append('registry: custom')
        if metrics_meta.get('reset'):
            metrics_lines.append('reset: true')
    # Layout width
    sections = {
        'Core': core_lines,
        'Components': comp_lines or ['(none)'],
        'Health Checks': chk_lines or ['(none)'],
    }
    if metrics_lines:
        sections['Metrics'] = metrics_lines

    inner_width = max(len(strip_ansi(line)) for lines in sections.values() for line in lines)
    # Enforce a minimum width
    inner_width = max(inner_width, 60)

    rendered: list[str] = []
    for title, lines in sections.items():
        rendered.extend(build_section(title, lines, inner_width))
        rendered.append('')
    # Remove trailing blank
    if rendered and rendered[-1] == '':
        rendered.pop()

    # Wrap with box
    clean_width = max(len(strip_ansi(r)) for r in rendered)
    top = BORDER_TL + BORDER_H * (clean_width + 2) + BORDER_TR
    bottom = BORDER_BL + BORDER_H * (clean_width + 2) + BORDER_BR
    boxed = [top]
    for r in rendered:
        boxed.append(f"{BORDER_V} {pad(r, clean_width)} {BORDER_V}")
    boxed.append(bottom)
    panel = '\n'.join(boxed)
    if _needs_ascii_fallback():
        for k, v in _ASCII_FALLBACK.items():
            panel = panel.replace(k, v)
    return panel

__all__ = ['build_startup_panel']
