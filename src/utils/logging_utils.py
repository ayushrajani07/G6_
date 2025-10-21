"""Unified logging utilities for G6 Platform."""
from __future__ import annotations

import logging
import os
import sys

DEFAULT_FORMAT = '%(asctime)s - %(threadName)s - %(name)s - %(levelname)s - %(message)s'
# Minimal console format (message only) used for cleaner terminal output.
MINIMAL_CONSOLE_FORMAT = '%(message)s'

SUPPRESSED_LOGGERS = [
    'urllib3', 'requests', 'kiteconnect.connection'
]

def setup_logging(level: str = 'INFO', log_file: str | None = None, fmt: str = DEFAULT_FORMAT) -> logging.Logger:
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
        try:
            root.removeHandler(h)
            try:
                h.flush()
            except Exception:
                pass
            try:
                h.close()
            except Exception:
                pass
        except Exception:
            pass

    # Decide console format precedence: explicit fmt parameter beats env toggles.
    try:
        from src.utils.env_flags import is_truthy_env  # type: ignore
        verbose_console_env = is_truthy_env('G6_VERBOSE_CONSOLE')
        minimal_disabled_env = is_truthy_env('G6_DISABLE_MINIMAL_CONSOLE')
        json_console_env = is_truthy_env('G6_JSON_LOGS')
    except Exception:
        verbose_console_env = bool(os.environ.get('G6_VERBOSE_CONSOLE'))
        minimal_disabled_env = bool(os.environ.get('G6_DISABLE_MINIMAL_CONSOLE'))
        json_console_env = bool(os.environ.get('G6_JSON_LOGS'))
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
    if json_console_env:
        try:
            try:
                import orjson as _orjson  # type: ignore
                _json_dumps = _orjson.dumps
                _is_orjson = True
            except Exception:  # pragma: no cover
                import json as _json  # type: ignore
                _json_dumps = _json.dumps
                _is_orjson = False

            class _JsonFormatter(logging.Formatter):
                def format(self, record: logging.LogRecord) -> str:  # type: ignore[override]
                    # Use record.created or fall back to time.time() to avoid naive datetime usage
                    import time as _time
                    # Pull structured context if available
                    try:
                        from . import log_context as _lc  # type: ignore
                        ctx = _lc.get_context()
                    except Exception:
                        ctx = {}
                    payload = {
                        'ts': getattr(record, 'created', _time.time()),
                        'level': record.levelname,
                        'logger': record.name,
                        'thread': record.threadName,
                        'msg': record.getMessage(),
                        'ctx': ctx or None,
                    }
                    if record.exc_info:
                        payload['exc_info'] = self.formatException(record.exc_info)
                    try:
                        if _is_orjson:
                            return _json_dumps(payload).decode('utf-8')  # type: ignore[call-arg]
                        else:
                            s = _json_dumps(payload)  # type: ignore[call-arg]
                            return s if isinstance(s, str) else str(s)
                    except Exception:
                        return str(payload)
            console.setFormatter(_JsonFormatter())
        except Exception:
            console.setFormatter(logging.Formatter(console_fmt))
    else:
        # Enrich plain text logs with selected context fields by adding a filter
        class _CtxFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
                try:
                    from . import log_context as _lc  # type: ignore
                    ctx = _lc.get_context()
                    # Expose as attributes for formatters that include them
                    for k in ("run_id", "component", "cycle", "index", "provider"):
                        if k in ctx and not hasattr(record, k):
                            setattr(record, k, ctx[k])
                except Exception:
                    pass
                return True
        console.addFilter(_CtxFilter())
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
            fh = logging.FileHandler(log_file, encoding='utf-8')
            fh.setLevel(log_level)
            # Always keep detailed format in file for post-mortem analysis
            class _FileCtxFilter(logging.Filter):
                def filter(self, record: logging.LogRecord) -> bool:  # type: ignore[override]
                    try:
                        from . import log_context as _lc  # type: ignore
                        ctx = _lc.get_context()
                        for k in ("run_id", "component", "cycle", "index", "provider"):
                            if k in ctx and not hasattr(record, k):
                                setattr(record, k, ctx[k])
                    except Exception:
                        pass
                    return True
            fh.addFilter(_FileCtxFilter())
            fh.setFormatter(logging.Formatter(DEFAULT_FORMAT))
            root.addHandler(fh)
        except Exception as e:
            root.error(f"Failed to create log file handler: {e}")
            try:
                from src.error_handling import handle_api_error  # late import
                handle_api_error(e, component="utils.logging_utils", context={"op": "create_file_handler", "path": log_file})
            except Exception:
                pass

    for name in SUPPRESSED_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    return root

# Best-effort cleanup of logging handlers at interpreter exit to avoid ResourceWarnings in tests
try:
    import atexit
    @atexit.register
    def _g6_close_logging_handlers() -> None:
        # Do not import or call any logging or error-handling code here.
        # During interpreter shutdown, streams may already be closed; simply
        # attempt a quiet flush/close and swallow any exceptions.
        try:
            root = logging.getLogger()
            for h in root.handlers[:]:
                try:
                    # Some handlers may already have closed streams; ignore errors
                    h.flush()
                except Exception:
                    pass
                try:
                    h.close()
                except Exception:
                    pass
        except Exception:
            # Final safety net: never raise during shutdown
            pass
except Exception:
    pass

__all__ = ["setup_logging"]
