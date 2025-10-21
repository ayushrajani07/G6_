"""Simple colorized logging utilities.

Automatically applies ANSI colors to log level names when outputting to a TTY.
Falls back to plain formatting when:
  * Not a TTY
  * Windows terminal without ANSI support (best effort detection)
  * G6_NO_COLOR is set (any truthy value)

Usage:
    from src.utils.color_logging import enable_color_logging
    enable_color_logging()

Colors (default):
  DEBUG: dim
  INFO: green
  WARNING: yellow
  ERROR: red
  CRITICAL: bold red background

Safe to call multiple times (idempotent).
"""
from __future__ import annotations

import logging
import os
import sys

try:
    from src.collectors.env_adapter import get_str as _env_get_str  # type: ignore
except Exception:  # pragma: no cover
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
FG_RED = "\x1b[31m"
FG_GREEN = "\x1b[32m"
FG_YELLOW = "\x1b[33m"
FG_BLUE = "\x1b[34m"
FG_MAGENTA = "\x1b[35m"
FG_CYAN = "\x1b[36m"
FG_WHITE = "\x1b[37m"
BG_RED = "\x1b[41m"
BG_BLUE = "\x1b[44m"
BG_MAGENTA = "\x1b[45m"
BG_YELLOW = "\x1b[43m"


def _build_themes() -> dict:
    return {
        'default': {
            "DEBUG": DIM + FG_GREEN,
            "INFO": FG_GREEN,
            "WARNING": FG_YELLOW,
            "ERROR": FG_RED,
            "CRITICAL": BOLD + FG_RED + BG_RED,
        },
        'vivid': {
            "DEBUG": FG_CYAN,
            "INFO": FG_GREEN + BOLD,
            "WARNING": BOLD + FG_YELLOW,
            "ERROR": BOLD + FG_RED,
            "CRITICAL": BOLD + FG_WHITE + BG_RED,
        },
        'high_contrast': {
            "DEBUG": FG_WHITE + BG_BLUE,
            "INFO": FG_WHITE + BG_MAGENTA,
            "WARNING": "\x1b[30m" + BG_YELLOW,  # black on yellow
            "ERROR": FG_WHITE + BG_RED,
            "CRITICAL": BOLD + FG_WHITE + BG_RED,
        },
        'muted': {
            "DEBUG": DIM + FG_CYAN,
            "INFO": DIM + FG_GREEN,
            "WARNING": DIM + FG_YELLOW,
            "ERROR": FG_RED,  # keep strong
            "CRITICAL": BOLD + FG_RED,
        },
        'mono': {
            "DEBUG": '',
            "INFO": '',
            "WARNING": '',
            "ERROR": '',
            "CRITICAL": BOLD,
        },
    }


_THEMES = _build_themes()

_TAG_COLORS = {
    'startup': FG_CYAN,
    'launcher': FG_MAGENTA,
    'auth': FG_BLUE,
    'cycle': FG_GREEN,
    'metrics': FG_YELLOW,
}


class ColorFormatter(logging.Formatter):
    def __init__(self, fmt: str, datefmt: str | None = None, use_color: bool = True, theme: str = 'default'):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color
        self.theme = theme if theme in _THEMES else 'default'

    def _color_level(self, level: str) -> str:
        style = _THEMES.get(self.theme, _THEMES['default']).get(level, '')
        if not style:
            return level
        return f"{style}{level}{RESET}"

    def _color_tags(self, message: str) -> str:
        if not self.use_color:
            return message
        # Colorize leading [tag] tokens separated by space
        parts = message.split()
        i = 0
        while i < len(parts):
            p = parts[i]
            if p.startswith('[') and p.endswith(']') and len(p) > 2:
                tag = p.strip('[]').lower()
                color = _TAG_COLORS.get(tag)
                if color:
                    parts[i] = f"{color}{p}{RESET}"
                i += 1
            else:
                break  # stop at first non-tag token
        return ' '.join(parts)

    def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
        if self.use_color:
            original_level = record.levelname
            record.levelname = self._color_level(original_level)
            try:
                out = super().format(record)
            finally:
                record.levelname = original_level
            # Post-process message segment inside out (only the part after first ': ' following logger name pattern)
            try:
                msg = record.getMessage()
                colored_msg = self._color_tags(msg)
                if colored_msg != msg:
                    out = out[::-1].replace(msg[::-1], colored_msg[::-1], 1)[::-1]
            except Exception:
                pass
            return out
        return super().format(record)


_DEF_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"

_enabled = False


def _ansi_supported() -> bool:
    if _env_get_str('G6_NO_COLOR', ''):
        return False
    # Force disable on dumb terminals
    if _env_get_str('TERM', '') == 'dumb':
        return False
    # Windows 10+ typically supports ANSI in modern terminals; rely on isatty
    return sys.stdout.isatty() if hasattr(sys.stdout, 'isatty') else False


def enable_color_logging(format: str = _DEF_FORMAT) -> None:
    global _enabled
    if _enabled:
        return
    root = logging.getLogger()
    use_color = _ansi_supported()
    theme = _env_get_str('G6_LOG_COLOR_THEME', 'default').lower()
    if theme not in _THEMES:
        theme = 'default'
    # Determine log level from env (string like "INFO" or numeric); default INFO
    level_name = _env_get_str("G6_LOG_LEVEL", "INFO").strip()
    level = logging.INFO
    try:
        if level_name:
            if level_name.isdigit():
                level = int(level_name)
            else:
                level = getattr(logging, level_name.upper(), logging.INFO)
    except Exception:
        level = logging.INFO
    # Replace existing stream handlers' formatter; leave others unchanged
    for h in root.handlers:
        if isinstance(h, logging.StreamHandler):
            h.setFormatter(ColorFormatter(format, use_color=use_color, theme=theme))
    if not root.handlers:
        # basicConfig not yet called; configure now
        logging.basicConfig(level=level, format=format)
        # After basicConfig, update any created stream handlers
        if root.handlers:
            for h in root.handlers:
                if isinstance(h, logging.StreamHandler):
                    h.setFormatter(ColorFormatter(format, use_color=use_color, theme=theme))
    _enabled = True


__all__ = ["enable_color_logging", "ColorFormatter"]

