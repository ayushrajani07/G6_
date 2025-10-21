"""Placeholder enhanced color system (subset) -- safe minimal implementation.
Full version can be dropped in later; keeps API compatibility with utils.color.
"""
from __future__ import annotations

import os
import sys

RESET = "\x1b[0m"; BOLD = "\x1b[1m"
FG_RED = "\x1b[31m"; FG_GREEN = "\x1b[32m"; FG_YELLOW = "\x1b[33m"; FG_CYAN = "\x1b[36m"; FG_MAGENTA = "\x1b[35m"; FG_WHITE = "\x1b[37m"
FG_BRIGHT_GREEN = "\x1b[92m"; FG_BRIGHT_RED = "\x1b[91m"; FG_BRIGHT_YELLOW = "\x1b[93m"; FG_BRIGHT_CYAN = "\x1b[96m"; FG_BRIGHT_BLACK = "\x1b[90m"; FG_BRIGHT_WHITE = "\x1b[97m"

_ENV = os.environ.get('G6_COLOR','auto').lower()

def _tty():
    try: return sys.stdout.isatty()
    except Exception: return False

def colors_enabled():
    if _ENV in ('0','false','no','off'): return False
    if _ENV in ('1','true','on','force'): return True
    return _tty()

def colorize(text: str, color: str = "", bold: bool = False, dim: bool = False, underline: bool = False, background: str = "") -> str:
    if not colors_enabled(): return text
    seq = ''
    if bold: seq += BOLD
    seq += color
    return f"{seq}{text}{RESET}"

_STATUS_MAP = {
    'healthy': (FG_BRIGHT_GREEN, True), 'ok': (FG_GREEN, False), 'ready': (FG_BRIGHT_GREEN, True),
    'warn': (FG_YELLOW, True), 'warning': (FG_YELLOW, True), 'degraded': (FG_YELLOW, True),
    'error': (FG_BRIGHT_RED, True), 'fail': (FG_BRIGHT_RED, True), 'failed': (FG_BRIGHT_RED, True),
    'critical': (FG_BRIGHT_RED, True), 'na': (FG_BRIGHT_BLACK, False), 'unknown': (FG_MAGENTA, True),
}

def status_color(status: str) -> tuple[str,bool]:
    s = (status or '').lower()
    return _STATUS_MAP.get(s, (FG_MAGENTA, True))

TERMINAL_CAPS = {'unicode': True, 'color': colors_enabled()}

__all__ = ['colorize','status_color','RESET','BOLD','FG_GREEN','FG_RED','FG_YELLOW','FG_CYAN','FG_MAGENTA','FG_WHITE','FG_BRIGHT_GREEN','FG_BRIGHT_RED','FG_BRIGHT_YELLOW','FG_BRIGHT_CYAN','FG_BRIGHT_BLACK','FG_BRIGHT_WHITE','TERMINAL_CAPS']
