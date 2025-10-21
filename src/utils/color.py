#!/usr/bin/env python3
"""Lightweight ANSI color utilities with env-based enable/disable.

Env var G6_COLOR controls behavior:
  0/false/off  -> disabled
  1/true/on    -> force color even if not tty
  force        -> same as on
  auto (default) -> enable only if stdout is a tty
"""
from __future__ import annotations

import os
import sys

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
FG_RED = "\x1b[31m"
FG_GREEN = "\x1b[32m"
FG_YELLOW = "\x1b[33m"
FG_MAGENTA = "\x1b[35m"

_ENV = os.environ.get('G6_COLOR', 'auto').lower()

def _detect_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False

def colors_enabled() -> bool:
    if _ENV in ('0','false','no','off'):
        return False
    if _ENV in ('1','true','on','force'):
        return True
    # auto
    return _detect_tty()

def colorize(text: str, color: str, bold: bool = False) -> str:
    if not colors_enabled():
        return text
    prefix = ''
    if bold:
        prefix += BOLD
    prefix += color
    return f"{prefix}{text}{RESET}"

def severity_color(status: str) -> tuple[str,bool]:
    """Map status tokens to (color, bold) preference."""
    s = status.upper()
    if 'STALL' in s or 'NO_DATA' in s:
        return FG_RED, True
    if 'DEGRADED' in s:
        return FG_YELLOW, True
    if 'OK' == s:
        return FG_GREEN, False
    # default
    return FG_MAGENTA, True

__all__ = ['colorize','severity_color','colors_enabled','FG_RED','FG_GREEN','FG_YELLOW','FG_MAGENTA','BOLD','RESET']
