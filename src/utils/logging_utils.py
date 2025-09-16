"""Unified logging utilities for G6 Platform."""
from __future__ import annotations
import logging, os, sys
from typing import Optional

DEFAULT_FORMAT = '%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s'
# Minimal console format (message only) used for cleaner terminal output.
MINIMAL_CONSOLE_FORMAT = '%(message)s'

SUPPRESSED_LOGGERS = [
    'urllib3', 'requests', 'kiteconnect.connection'
]

def setup_logging(level: str = 'INFO', log_file: Optional[str] = None, fmt: str = DEFAULT_FORMAT) -> logging.Logger:
    """Configure root logging.

    Console handler: by default uses minimal message-only format to satisfy
    requirement: "REMOVE INFO- AND ALL TEXT BEFORE THAT FROM TERMINAL OUTPUT".
    Override via env G6_VERBOSE_CONSOLE=1 (restores full DEFAULT_FORMAT) or
    explicitly pass a fmt argument.

    File handler (if enabled) always uses full DEFAULT_FORMAT for diagnostics.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(log_level)
    # Remove existing handlers to avoid duplication on re-init
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Decide console format precedence: explicit fmt parameter beats env toggles.
    verbose_console_env = os.environ.get('G6_VERBOSE_CONSOLE', '').lower() in ('1','true','yes','on')
    minimal_disabled_env = os.environ.get('G6_DISABLE_MINIMAL_CONSOLE', '').lower() in ('1','true','yes','on')
    # If caller passed a custom fmt different from DEFAULT_FORMAT, honor it.
    if fmt != DEFAULT_FORMAT:
        console_fmt = fmt
    else:
        if verbose_console_env or minimal_disabled_env:
            console_fmt = DEFAULT_FORMAT
        else:
            console_fmt = MINIMAL_CONSOLE_FORMAT

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(log_level)
    console.setFormatter(logging.Formatter(console_fmt))
    try:
        enc = getattr(sys.stdout, 'encoding', '') or ''
        if enc.lower() not in ('utf-8','utf8','utf_8'):
            class _AsciiSanitizer(logging.Filter):
                _MAP = str.maketrans({
                    '╔':'+','╗':'+','╚':'+','╝':'+','═':'=','║':'|','─':'-','┌':'+','┐':'+','└':'+','┘':'+','│':'|'
                })
                def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
                    if isinstance(record.msg, str):
                        record.msg = record.msg.translate(self._MAP)
                    return True
            console.addFilter(_AsciiSanitizer())
    except Exception:
        pass
    root.addHandler(console)

    if log_file:
        try:
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            fh = logging.FileHandler(log_file)
            fh.setLevel(log_level)
            # Always keep detailed format in file for post-mortem analysis
            fh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
            root.addHandler(fh)
        except Exception as e:
            root.error(f"Failed to create log file handler: {e}")

    for name in SUPPRESSED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return root

__all__ = ["setup_logging"]
