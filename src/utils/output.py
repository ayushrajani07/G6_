from __future__ import annotations

import json
import logging
import os
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Protocol, Union

try:
    # Prefer central env adapter for consistency
    from src.collectors.env_adapter import get_bool as _env_get_bool
    from src.collectors.env_adapter import get_float as _env_get_float
    from src.collectors.env_adapter import get_int as _env_get_int
    from src.collectors.env_adapter import get_str as _env_get_str  # type: ignore
except Exception:  # pragma: no cover
    # Safe fallbacks if adapter not available early in import graph
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default
    def _env_get_bool(name: str, default: bool = False) -> bool:
        try:
            v = os.getenv(name)
            if v is None:
                return default
            return v.strip().lower() in {"1","true","yes","on","y"}
        except Exception:
            return default
    def _env_get_int(name: str, default: int) -> int:
        try:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return int(str(v).strip())
        except Exception:
            return default
    def _env_get_float(name: str, default: float) -> float:
        try:
            v = os.getenv(name)
            if v is None or str(v).strip() == "":
                return default
            return float(str(v).strip())
        except Exception:
            return default

# Backward-compat shim for existing truthy checks used in this module
def is_truthy_env(name: str) -> bool:
    return _env_get_bool(name, False)

# Optional Rich support
try:
    import rich.console as _rich_console
except Exception:  # pragma: no cover
    _rich_console = None  # type: ignore[assignment]


# ------------------------------
# Data model
# ------------------------------

JsonLike = Union[None, str, int, float, bool, Sequence["JsonLike"], Mapping[str, "JsonLike"]]


@dataclass
class OutputEvent:
    timestamp: str
    level: str
    message: str
    scope: str | None = None
    tags: list[str] | Mapping[str, str] | None = None
    data: JsonLike | None = None
    # Allow attaching arbitrary extras without breaking sinks
    extra: Mapping[str, Any] | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")


# ------------------------------
# Public atomic-write helpers (Windows-safe)
# ------------------------------

def atomic_replace(src_path: str, dst_path: str, retries: int = 20, delay: float = 0.05) -> None:
    """Atomically replace dst with src, retrying on Windows file-lock errors.

    Test Fast Path:
      If env G6_TEST_FAST_IO=1 is set, drastically reduce retries & delay to
      avoid long stalls under CI / local Windows where pervasive file locking
      (AV / indexers) is not expected or acceptable for tests. Optional trace
      logging when G6_TEST_FAST_IO_TRACE=1.
    """
    import time as _time

    fast = _env_get_bool("G6_TEST_FAST_IO", False)
    if fast:
        # Keep a couple quick retries to tolerate a transient race but cap total wait ~<20ms.
        retries = min(retries, 3)
        delay = min(delay, 0.005)
    trace = fast and _env_get_bool("G6_TEST_FAST_IO_TRACE", False)

    for attempt in range(max(1, int(retries))):
        try:
            os.replace(src_path, dst_path)
            if trace:
                print(f"[fast-io] atomic_replace success attempt={attempt+1} dst={dst_path}")
            return
        except (PermissionError, OSError) as e:  # noqa: PERF203 fine here
            if attempt + 1 >= retries:
                break
            if trace:
                print(f"[fast-io] atomic_replace retry attempt={attempt+1} err={e} dst={dst_path}")
            _time.sleep(delay)
    # Last attempt (raise if fails)
    os.replace(src_path, dst_path)


def atomic_write_json(dst_path: str, payload: dict[str, Any], *, ensure_ascii: bool = False, indent: int = 2, retries: int = 20, delay: float = 0.05) -> None:
    """Write JSON to a file atomically, with fsync and Windows-safe retry replace.

    - Writes to <dst>.tmp, flushes and fsyncs, then replaces dst.
    - Creates parent directories when missing.
    """
    # Ensure directory exists
    try:
        os.makedirs(os.path.dirname(dst_path) or ".", exist_ok=True)
    except Exception:
        pass
    fast = _env_get_bool("G6_TEST_FAST_IO", False)
    tmp = dst_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=ensure_ascii, default=str, indent=indent)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            # Best-effort: on some FS, fsync may not be available
            pass
    # Propagate possibly reduced retries/delay in fast mode
    if fast:
        retries = min(retries, 3)
        delay = min(delay, 0.005)
    atomic_replace(tmp, dst_path, retries=retries, delay=delay)


# ------------------------------
# Sink protocol and implementations
# ------------------------------

class OutputSink(Protocol):
    def emit(self, event: OutputEvent) -> None:  # pragma: no cover - protocol
        ...


class StdoutSink:
    def __init__(self, stream: Any = sys.stdout) -> None:
        self._stream = stream

    def emit(self, event: OutputEvent) -> None:
        # Compact human string with optional JSON payload
        # Ensure level token is uppercased for visibility and tests
        base = f"[{event.level.upper()}] {event.message}"
        if event.scope:
            base = f"({event.scope}) " + base
        if event.tags:
            base += f" tags={event.tags}"
        if event.data is not None:
            try:
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
            except Exception:
                payload = str(event.data)
            base += f" data={payload}"
        # Write directly to the configured stream to avoid global print() suppression hooks
        try:
            self._stream.write(base + "\n")
        except Exception:
            # Fallback to print if stream.write unavailable
            print(base, file=self._stream)
        # Best-effort flush for custom streams (e.g., StringIO) to ensure immediate visibility in tests
        try:
            flush = getattr(self._stream, 'flush', None)
            if callable(flush):
                flush()
        except Exception:
            pass


class LoggingSink:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("g6")
        # If no handlers are configured, default to a basic stream handler
        if not self._logger.handlers:
            logging.basicConfig(level=logging.INFO)

    def emit(self, event: OutputEvent) -> None:
        lvl_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "success": logging.INFO,
            "warning": logging.WARNING,
            "warn": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        lvl = lvl_map.get(event.level.lower(), logging.INFO)
        msg = event.message
        extra = {
            "scope": event.scope,
            "tags": event.tags,
            "data": event.data,
            **(event.extra or {}),
        }
        try:
            self._logger.log(lvl, msg, extra=extra)
        except Exception:
            # Fallback without extras if logger is strict
            self._logger.log(lvl, msg)

# ---------------
# Colorizing Filter (applies to standard logging handlers not using Rich)
# ---------------
class _ColorizingFilter(logging.Filter):  # pragma: no cover (cosmetic)
    LEVEL_COLORS = {
        logging.DEBUG: '\x1b[2m',          # dim
        logging.INFO: '\x1b[36m',           # cyan
        logging.WARNING: '\x1b[33m',       # yellow
        logging.ERROR: '\x1b[31m',         # red
        logging.CRITICAL: '\x1b[1;41m',    # bold white on red bg
    }
    KEYWORD_COLORS = [
        ('success', '\x1b[32m'),  # green
        ('passed', '\x1b[32m'),
        ('fail', '\x1b[31m'),
        ('error', '\x1b[31m'),
        ('warning', '\x1b[33m'),
    ]
    RESET = '\x1b[0m'
    def __init__(self):
        super().__init__('g6.color_filter')
        self._tty = sys.stdout.isatty() if hasattr(sys.stdout, 'isatty') else False
        self._mode = _env_get_str('G6_LOG_COLOR_MODE','auto').lower()
        if self._mode not in {'auto','on','off'}:
            self._mode = 'auto'
        if self._mode == 'off':
            self._enabled = False
        elif self._mode == 'on':
            self._enabled = True
        else:  # auto
            self._enabled = self._tty
        # Allow explicit force (overrides auto/tty) mainly for Windows terminals supporting ANSI
        if is_truthy_env('G6_LOG_COLOR_FORCE'):
            self._enabled = True
        # Windows ANSI enable (best-effort)
        if self._enabled and os.name == 'nt':
            try:
                import colorama  # type: ignore
                colorama.just_fix_windows_console()  # initialize if available
            except Exception:
                pass
    def filter(self, record: logging.LogRecord) -> bool:
        if not self._enabled:
            return True
        try:
            msg = record.getMessage()
            base_color = self.LEVEL_COLORS.get(record.levelno)
            if base_color:
                # Apply keyword highlight precedence: if keyword found, override base color
                lower_msg = msg.lower()
                for kw, col in self.KEYWORD_COLORS:
                    if kw in lower_msg:
                        base_color = col
                        break
                record.msg = f"{base_color}{msg}{self.RESET}"  # type: ignore[assignment]
        except Exception:
            pass
        return True

def _install_color_filter():  # pragma: no cover (runtime cosmetic)
    try:
        # Avoid if Rich sink likely handling color (Rich provides own styling)
        sinks_env = _env_get_str('G6_OUTPUT_SINKS','stdout,logging').lower()
        if 'rich' in sinks_env:
            return
        root = logging.getLogger()
        if any(isinstance(f, _ColorizingFilter) for f in getattr(root,'filters',[])):
            return
        root.addFilter(_ColorizingFilter())
    except Exception:
        pass


class RichSink:
    def __init__(self, console: Any | None = None) -> None:
        if console is not None:
            self._console = console
        elif _rich_console is not None:
            try:
                self._console = _rich_console.Console()
            except Exception:  # pragma: no cover
                self._console = None
        else:
            self._console = None

    def emit(self, event: OutputEvent) -> None:
        if not self._console:
            return  # rich not available -> no-op
        style = {
            "debug": "dim",
            "info": "",
            "success": "green",
            "warning": "yellow",
            "warn": "yellow",
            "error": "red",
            "critical": "bold red",
        }.get(event.level.lower(), "")
        payload = ""
        if event.data is not None:
            try:
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
            except Exception:
                payload = str(event.data)
            payload = f"\n[data]\n{payload}"
        tags = f" tags={event.tags}" if event.tags else ""
        scope = f"({event.scope}) " if event.scope else ""
        self._console.print(f"{scope}[{style}]{event.level.upper()}[/] {event.message}{tags}{payload}")


class JsonlSink:
    def __init__(self, path: str) -> None:
        self._path = path
        # Ensure directory exists lazily on first write

    def emit(self, event: OutputEvent) -> None:
        rec = asdict(event)
        try:
            line = json.dumps(rec, ensure_ascii=False, default=str)
        except Exception:
            # As last resort, stringify data
            rec["data"] = str(event.data)
            line = json.dumps(rec, ensure_ascii=False, default=str)
        # Open per write to avoid file handle lifetime/locking issues
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


class MemorySink:
    def __init__(self) -> None:
        self.events: list[OutputEvent] = []

    def emit(self, event: OutputEvent) -> None:
        self.events.append(event)


class PanelFileSink:
    """Writes per-panel JSON files for the summarizer to consume later.

    Enabled by adding 'panels' to G6_OUTPUT_SINKS.
    Config:
      - G6_PANELS_DIR: base directory to write panel files (default: data/panels)
      - G6_PANELS_INCLUDE: CSV of panel names to include (upper/lower ignored). If empty => allow all.
      - G6_PANELS_ATOMIC: true/false, atomic replace writes (default true)
    Usage via router.panel_update(panel, data, kind=optional)
    """
    def __init__(self, base_dir: str, include: Iterable[str] | None = None, atomic: bool = True) -> None:
        self._base_dir = base_dir
        self._include = {s.strip().lower() for s in include} if include else None
        self._atomic = bool(atomic)
        # Control meta emission (default on)
        self._always_meta = _env_get_bool("G6_PANELS_ALWAYS_META", True)
        # Optional schema wrapper gate (v1 wrapper adds version + emitted_at and nests legacy payload under 'panel')
        self._schema_wrapper = _env_get_bool("G6_PANELS_SCHEMA_WRAPPER", False)
        # Transaction staging directory (per-txn subfolders)
        self._txn_root = os.path.join(self._base_dir, ".txn")
        # Ensure base dir exists early to make commit meta writes reliable
        try:
            os.makedirs(self._base_dir, exist_ok=True)
        except Exception:
            pass

    def _mark_health(self, ok: bool) -> None:
        """Optional graded health for panels file sink (env-gated)."""
        try:
            if not is_truthy_env('G6_HEALTH_COMPONENTS'):
                return
            from src.health import runtime as health_runtime  # lazy import
            from src.health.models import HealthLevel, HealthState
            if ok:
                health_runtime.set_component('panels_sink', HealthLevel.HEALTHY, HealthState.HEALTHY)
            else:
                health_runtime.set_component('panels_sink', HealthLevel.WARNING, HealthState.WARNING)
        except Exception:
            pass

    def close(self) -> None:  # pragma: no cover - simple cleanup
        # Best-effort: remove any empty staging directories to avoid test contamination
        try:
            if os.path.isdir(self._txn_root) and not os.listdir(self._txn_root):
                import shutil as _sh
                _sh.rmtree(self._txn_root, ignore_errors=True)
        except Exception:
            pass

    def _allowed(self, panel: str) -> bool:
        return True if self._include is None else (panel.lower() in self._include)

    @staticmethod
    def _atomic_replace(src_path: str, dst_path: str, retries: int = 20, delay: float = 0.05) -> None:
        # Delegate to public helper for consistency
        atomic_replace(src_path, dst_path, retries=retries, delay=delay)

    def _write_json_atomic(self, dst: str, payload: dict[str, Any]) -> None:
        # Ensure directory exists
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
        except Exception:
            pass
        tmp = dst + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str, indent=2)
            try:
                f.flush()
                os.fsync(f.fileno())
            except Exception:
                pass
        if self._atomic:
            self._atomic_replace(tmp, dst)
        else:
            # Best-effort non-atomic replace
            os.replace(tmp, dst)

    def _txn_dir(self, txn_id: str) -> str:
        return os.path.join(self._txn_root, str(txn_id))

    def _txn_dst(self, txn_id: str, panel_s: str) -> str:
        return os.path.join(self._txn_dir(txn_id), f"{panel_s}.json")

    def emit(self, event: OutputEvent) -> None:
        # Only handle events produced by router.panel_update (extra has _panel)
        extra = event.extra or {}
        # Transaction control path
        txn_id = None
        txn_action = None
        try:
            if isinstance(extra, dict):
                txn_id = extra.get("_txn_id")
                txn_action = extra.get("_txn_action")
        except Exception:
            txn_id = None
            txn_action = None
        if txn_action in ("commit", "abort") and txn_id:
            # Handle commit/abort for a staged transaction
            try:
                if txn_action == "commit":
                    stage_dir = self._txn_dir(str(txn_id))
                    committed: list[str] = []
                    diag_env = _env_get_str("G6_PANELS_TXN_DEBUG", "")
                    # Optional auto-debug now gated by explicit env to avoid default noise in CI
                    if not diag_env and _env_get_str('PYTEST_CURRENT_TEST','') and is_truthy_env('G6_PANELS_TXN_AUTO_DEBUG'):
                        diag_env = '1'
                    diag = diag_env not in ("","0","false","no","off")
                    if diag:
                        try:
                            print(f"[panels-txn-debug] commit_start id={txn_id} stage_dir={stage_dir} present={os.path.isdir(stage_dir)} contents={os.listdir(stage_dir) if os.path.isdir(stage_dir) else 'NA'}")
                        except Exception:
                            pass
                    if os.path.isdir(stage_dir):
                        # Robust copy strategy instead of move to tolerate transient Windows locks.
                        for name in list(os.listdir(stage_dir)):
                            if not name.endswith('.json'):
                                continue
                            src = os.path.join(stage_dir, name)
                            dst = os.path.join(self._base_dir, name)
                            try:
                                os.makedirs(self._base_dir, exist_ok=True)
                            except Exception:
                                pass
                            try:
                                # Copy contents (do not remove staging yet) so a later retry path can still read.
                                with open(src, encoding='utf-8') as _rf, open(dst + '.tmpcopy', 'w', encoding='utf-8') as _wf:
                                    _wf.write(_rf.read())
                                # Atomic-ish replace of final target
                                try:
                                    if os.path.exists(dst):
                                        os.remove(dst)
                                except Exception:
                                    pass
                                try:
                                    os.replace(dst + '.tmpcopy', dst)
                                except Exception:
                                    # Last resort: simple copy if replace failed
                                    try:
                                        import shutil as _sh
                                        _sh.copyfile(src, dst)
                                    except Exception:
                                        pass
                                committed.append(name[:-5])
                            except Exception:
                                # Best-effort: leave uncommitted; fallback below may still rescue
                                try:
                                    if os.path.exists(dst + '.tmpcopy'):
                                        os.remove(dst + '.tmpcopy')
                                except Exception:
                                    pass
                    else:
                        # Staging missing unexpectedly; emit debug trace if enabled
                        if is_truthy_env('G6_PANELS_TXN_DEBUG'):
                            print(f"[panels-txn-debug] commit stage_dir_missing id={txn_id} dir={stage_dir}")
                    # Secondary safety: if nothing committed but stage exists, attempt relaxed copy
                    if not committed and os.path.isdir(stage_dir):
                        try:
                            for name in os.listdir(stage_dir):
                                if not name.endswith('.json'):
                                    continue
                                src = os.path.join(stage_dir, name)
                                dst = os.path.join(self._base_dir, name)
                                try:
                                    with open(src,encoding='utf-8') as _rf, open(dst,'w',encoding='utf-8') as _wf:
                                        _wf.write(_rf.read())
                                    committed.append(name[:-5])
                                except Exception:
                                    pass
                        except Exception:
                            pass
                    # Final verification: if after attempts some staged files still not present in base, try one last rescue copy
                    try:
                        if os.path.isdir(stage_dir):
                            for name in os.listdir(stage_dir):
                                if not name.endswith('.json'):
                                    continue
                                dst = os.path.join(self._base_dir, name)
                                if not os.path.exists(dst):
                                    src = os.path.join(stage_dir, name)
                                    try:
                                        with open(src,encoding='utf-8') as _rf, open(dst,'w',encoding='utf-8') as _wf:
                                            _wf.write(_rf.read())
                                        if name[:-5] not in committed:
                                            committed.append(name[:-5])
                                        if diag:
                                            print(f"[panels-txn-debug] final_rescue_copied name={name} id={txn_id}")
                                    except Exception:
                                        if diag:
                                            print(f"[panels-txn-debug] final_rescue_failed name={name} id={txn_id}")
                                        pass
                    except Exception:
                        pass
                    if diag:
                        try:
                            print(f"[panels-txn-debug] commit_end id={txn_id} committed={committed} base_contents={os.listdir(self._base_dir) if os.path.isdir(self._base_dir) else 'NA'}")
                        except Exception:
                            pass
                    # Write/refresh meta with last transaction info (if enabled)
                    if self._always_meta:
                        try:
                            meta_path = os.path.join(self._base_dir, ".meta.json")
                            meta_payload = {
                                "last_txn_id": str(txn_id),
                                "committed_at": event.timestamp,
                                "panels": committed,
                            }
                            self._write_json_atomic(meta_path, meta_payload)
                        except Exception:
                            pass
                    # Cleanup staging dir
                    try:
                        import shutil as _sh
                        if os.path.isdir(self._txn_dir(str(txn_id))):
                            _sh.rmtree(self._txn_dir(str(txn_id)), ignore_errors=True)
                            # If deletion silently failed (Windows handle race), retry once after short sleep
                            if os.path.isdir(self._txn_dir(str(txn_id))):
                                import time as _t
                                _t.sleep(0.05)
                                try:
                                    _sh.rmtree(self._txn_dir(str(txn_id)), ignore_errors=True)
                                except Exception:
                                    pass
                        # If root .txn dir now empty remove it (helps abort test expectation)
                        try:
                            if os.path.isdir(self._txn_root) and not os.listdir(self._txn_root):
                                _sh.rmtree(self._txn_root, ignore_errors=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    # Mark healthy on successful commit (best-effort)
                    self._mark_health(True)
                    # Metrics: commit counter
                    try:
                        from src.metrics import get_metrics_singleton  # type: ignore
                        m = get_metrics_singleton()
                        if m and hasattr(m, 'panels_txn_commits'):
                            m.panels_txn_commits.inc()  # type: ignore[arg-type]
                    except Exception:
                        pass
                else:
                    # Abort -> delete staging dir
                    diag = is_truthy_env('G6_PANELS_TXN_DEBUG')
                    if diag:
                        try:
                            print(f"[panels-txn-debug] abort_start id={txn_id} path={self._txn_dir(str(txn_id))} exists={os.path.isdir(self._txn_dir(str(txn_id)))}")
                        except Exception:
                            pass
                    try:
                        import shutil as _sh
                        txn_path = self._txn_dir(str(txn_id))
                        _sh.rmtree(txn_path, ignore_errors=True)
                        # Retry window with exponential backoff (short) to accommodate Windows handles
                        if os.path.isdir(txn_path):
                            import time as _t
                            for _i in range(3):
                                _t.sleep(0.02 * (2 ** _i))
                                if not os.path.isdir(txn_path):
                                    break
                                _sh.rmtree(txn_path, ignore_errors=True)
                        # Remove root if empty
                        try:
                            if os.path.isdir(self._txn_root) and not os.listdir(self._txn_root):
                                _sh.rmtree(self._txn_root, ignore_errors=True)
                        except Exception:
                            pass
                    except Exception:
                        pass
                    if diag:
                        try:
                            print(f"[panels-txn-debug] abort_end id={txn_id} txn_exists={os.path.isdir(self._txn_dir(str(txn_id)))} root_exists={os.path.isdir(self._txn_root)} root_contents={os.listdir(self._txn_root) if os.path.isdir(self._txn_root) else 'NA'}")
                        except Exception:
                            pass
                    # Mark degraded on abort
                    self._mark_health(False)
                    # Metrics: abort counter
                    try:
                        from src.metrics import get_metrics_singleton  # type: ignore
                        m = get_metrics_singleton()
                        if m and hasattr(m, 'panels_txn_aborts'):
                            m.panels_txn_aborts.inc()  # type: ignore[arg-type]
                    except Exception:
                        pass
                return
            except Exception as e:
                # Fallback rescue: if commit failed, attempt best-effort copy then cleanup
                try:
                    if txn_action == 'commit':
                        stage_dir = self._txn_dir(str(txn_id))
                        if os.path.isdir(stage_dir):
                            for name in os.listdir(stage_dir):
                                if not name.endswith('.json'):
                                    continue
                                src = os.path.join(stage_dir, name)
                                dst = os.path.join(self._base_dir, name)
                                try:
                                    os.makedirs(self._base_dir, exist_ok=True)
                                    with open(src,encoding='utf-8') as _rf, open(dst,'w',encoding='utf-8') as _wf:
                                        _wf.write(_rf.read())
                                except Exception:
                                    pass
                            # Attempt meta write
                            if self._always_meta:
                                try:
                                    meta_path = os.path.join(self._base_dir, '.meta.json')
                                    meta_payload = {"last_txn_id": str(txn_id), "committed_at": event.timestamp, "panels": []}
                                    self._write_json_atomic(meta_path, meta_payload)
                                except Exception:
                                    pass
                            # Cleanup staging dir
                            try:
                                import shutil as _sh
                                _sh.rmtree(stage_dir, ignore_errors=True)
                            except Exception:
                                pass
                except Exception:
                    pass
                if is_truthy_env('G6_PANELS_TXN_DEBUG'):
                    try:
                        print(f"[panels-txn-debug] commit_exception id={txn_id} err={e}")
                    except Exception:
                        pass
                return

        panel = extra.get("_panel") if isinstance(extra, dict) else None
        if not panel:
            return
        panel_s = str(panel)
        if not self._allowed(panel_s):
            return
        mode = str(extra.get("_mode") or "update").lower()
        cap = extra.get("_cap")
        try:
            cap_n = int(cap) if cap is not None else None
        except Exception:
            cap_n = None
        # Destination: live or transaction staging
        in_txn = bool(txn_id)
        if in_txn:
            dst = self._txn_dst(str(txn_id), panel_s)
        else:
            try:
                os.makedirs(self._base_dir, exist_ok=True)
            except Exception:
                pass
            dst = os.path.join(self._base_dir, f"{panel_s}.json")
        try:
            # Load previous for append/extend
            prev_data = None
            if mode in ("append", "extend"):
                # Prefer staged file if present
                if os.path.exists(dst):
                    try:
                        with open(dst, encoding="utf-8") as rf:
                            prev_obj = json.load(rf)
                        if isinstance(prev_obj, dict):
                            if "data" in prev_obj:
                                prev_data = prev_obj.get("data")
                            elif "panel" in prev_obj and isinstance(prev_obj.get("panel"), dict):  # wrapped schema
                                prev_data = prev_obj["panel"].get("data")  # type: ignore[index]
                    except Exception:
                        prev_data = None
                # If in a transaction and no stage file, seed from live file
                if prev_data is None and in_txn:
                    live = os.path.join(self._base_dir, f"{panel_s}.json")
                    if os.path.exists(live):
                        try:
                            with open(live, encoding="utf-8") as rf:
                                prev_obj2 = json.load(rf)
                            if isinstance(prev_obj2, dict):
                                if "data" in prev_obj2:
                                    prev_data = prev_obj2.get("data")
                                elif "panel" in prev_obj2 and isinstance(prev_obj2.get("panel"), dict):
                                    prev_data = prev_obj2["panel"].get("data")  # type: ignore[index]
                        except Exception:
                            prev_data = None

            new_data = event.data
            if mode == "append":
                items = []
                if isinstance(prev_data, list):
                    items = list(prev_data)
                elif isinstance(prev_data, dict):
                    prev_items = prev_data.get("items")
                    if isinstance(prev_items, list):
                        items = list(prev_items)
                items.append(new_data)
                if cap_n is not None and cap_n > 0:
                    items = items[-cap_n:]
                new_data = items
            elif mode == "extend":
                items = []
                if isinstance(prev_data, list):
                    items = list(prev_data)
                elif isinstance(prev_data, dict):
                    prev_items = prev_data.get("items")
                    if isinstance(prev_items, list):
                        items = list(prev_items)
                if isinstance(new_data, list):
                    items.extend(new_data)
                else:
                    items.append(new_data)
                if cap_n is not None and cap_n > 0:
                    items = items[-cap_n:]
                new_data = items

            legacy_payload = {
                "panel": panel_s,
                "updated_at": event.timestamp,
                "kind": extra.get("_kind"),
                "data": new_data,
            }
            if self._schema_wrapper:
                try:
                    import datetime as _dt
                    ts_val = event.timestamp
                    if isinstance(ts_val, str):
                        try:
                            ts_val = float(ts_val)
                        except Exception:
                            ts_val = None
                    iso_ts = _dt.datetime.fromtimestamp(float(ts_val), _dt.UTC).isoformat().replace('+00:00','Z') if isinstance(ts_val, (int,float)) else None
                except Exception:
                    iso_ts = None  # best-effort
                # Import version constant lazily to avoid import cycles
                try:
                    from src.panels.version import PANEL_SCHEMA_VERSION as _PANEL_SCHEMA_VERSION  # type: ignore
                except Exception:  # pragma: no cover - extreme fallback
                    _PANEL_SCHEMA_VERSION = 1  # default if missing
                payload = {
                    # Keep legacy 'version' for backward compatibility (deprecated)
                    "version": _PANEL_SCHEMA_VERSION,
                    # New explicit schema version (authoritative)
                    "schema_version": _PANEL_SCHEMA_VERSION,
                    "emitted_at": iso_ts or event.timestamp,
                    "panel": legacy_payload,
                }
            else:
                payload = legacy_payload

            self._write_json_atomic(dst, payload)
            # Mark healthy on successful write
            self._mark_health(True)
            # Metrics: best-effort increment
            try:
                from src.metrics import get_metrics_singleton  # facade import
                m = get_metrics_singleton()
                if m and hasattr(m, 'panels_writes'):
                    m.panels_writes.inc()  # type: ignore[call-arg]
                # Panel update counters by mode
                if m and hasattr(m, 'panels_updates_total'):
                    try:
                        m.panels_updates_total.labels(mode).inc()  # type: ignore[arg-type]
                    except Exception:
                        pass
            except Exception:
                pass
        except Exception:
            # Swallow sink exceptions
            # Degraded on failure
            self._mark_health(False)
            # Metrics: best-effort error increment
            try:
                from src.metrics import get_metrics_singleton  # facade import
                m = get_metrics_singleton()
                if m and hasattr(m, 'panels_write_errors'):
                    m.panels_write_errors.inc()  # type: ignore[call-arg]
            except Exception:
                pass


# ------------------------------
# Router
# ------------------------------

_LEVEL_ORDER = {
    "debug": 10,
    "info": 20,
    "success": 20,
    "warning": 30,
    "warn": 30,
    "error": 40,
    "critical": 50,
}


def _normalize_level(level: str) -> str:
    l = level.lower()
    if l == "warn":
        return "warning"
    if l not in _LEVEL_ORDER:
        return "info"
    return l


class OutputRouter:
    def __init__(self, sinks: list[OutputSink] | None = None, min_level: str = "info") -> None:
        self._sinks: list[OutputSink] = list(sinks or [])
        self._min_level = _normalize_level(min_level)
        # Maintain a simple transaction stack for panel writes
        self._panel_txn_stack: list[str] = []

    def add_sink(self, sink: OutputSink) -> None:
        self._sinks.append(sink)

    def set_min_level(self, level: str) -> None:
        self._min_level = _normalize_level(level)

    def should_emit(self, level: str) -> bool:
        return _LEVEL_ORDER[_normalize_level(level)] >= _LEVEL_ORDER[self._min_level]

    def emit(
        self,
        message: str,
        *,
        level: str = "info",
        scope: str | None = None,
        tags: list[str] | Mapping[str, str] | None = None,
        data: JsonLike | None = None,
        extra: Mapping[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> None:
        level_n = _normalize_level(level)
        if not self.should_emit(level_n):
            return
        evt = OutputEvent(
            timestamp=timestamp or OutputEvent.now_iso(),
            level=level_n,
            message=message,
            scope=scope,
            tags=tags,
            data=data,
            extra=extra,
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                # Sinks should not break others
                try:
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)
                except Exception:
                    pass

    # Convenience level methods
    def debug(self, msg: str, **kw: Any) -> None: self.emit(msg, level="debug", **kw)
    def info(self, msg: str, **kw: Any) -> None: self.emit(msg, level="info", **kw)
    def success(self, msg: str, **kw: Any) -> None: self.emit(msg, level="success", **kw)
    def warning(self, msg: str, **kw: Any) -> None: self.emit(msg, level="warning", **kw)
    def error(self, msg: str, **kw: Any) -> None: self.emit(msg, level="error", **kw)
    def critical(self, msg: str, **kw: Any) -> None: self.emit(msg, level="critical", **kw)

    # Panel update helper: directs to panel sinks without printing human output
    def panel_update(self, panel: str, data: JsonLike, *, kind: str | None = None) -> None:
        # Attach txn context if any
        extra_base: dict[str, Any] = {"_panel": panel}
        if kind:
            extra_base["_kind"] = kind
        if self._panel_txn_stack:
            extra_base["_txn_id"] = self._panel_txn_stack[-1]
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_update:{panel}",
            scope="panel",
            tags=None,
            data=data,
            extra=extra_base,
        )
        for s in self._sinks:
            try:
                # Only sinks that care (e.g., PanelFileSink) will act
                s.emit(evt)
            except Exception:
                try:
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)
                except Exception:
                    pass

    def panel_append(self, panel: str, item: JsonLike, *, cap: int = 100, kind: str | None = None) -> None:
        extra_base: dict[str, Any] = {"_panel": panel, "_mode": "append", "_cap": cap}
        if kind:
            extra_base["_kind"] = kind
        if self._panel_txn_stack:
            extra_base["_txn_id"] = self._panel_txn_stack[-1]
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_append:{panel}",
            scope="panel",
            tags=None,
            data=item,
            extra=extra_base,
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                try:
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)
                except Exception:
                    pass

    def panel_extend(self, panel: str, items: Sequence[JsonLike], *, cap: int = 100, kind: str | None = None) -> None:
        extra_base: dict[str, Any] = {"_panel": panel, "_mode": "extend", "_cap": cap}
        if kind:
            extra_base["_kind"] = kind
        if self._panel_txn_stack:
            extra_base["_txn_id"] = self._panel_txn_stack[-1]
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_extend:{panel}",
            scope="panel",
            tags=None,
            data=list(items),
            extra=extra_base,
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                try:
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)
                except Exception:
                    pass

    # ---------------
    # Panel transactions
    # ---------------
    class PanelsTransaction:
        def __init__(self, router: OutputRouter, txn_id: str | None = None) -> None:
            self._router = router
            self._txn_id = txn_id or str(uuid.uuid4())
            self._active = False
        @property
        def id(self) -> str:
            return self._txn_id
        def __enter__(self) -> OutputRouter.PanelsTransaction:
            self._router._panel_txn_stack.append(self._txn_id)
            self._active = True
            return self
        def commit(self) -> None:
            if not self._active:
                return
            self._router._panel_txn_stack.pop()
            # Tell sinks to commit this txn id
            self._router.emit(
                "panels_txn_commit",
                level="info",
                scope="panel",
                data=None,
                extra={"_txn_action": "commit", "_txn_id": self._txn_id},
            )
            self._active = False
        def abort(self) -> None:
            if not self._active:
                return
            self._router._panel_txn_stack.pop()
            # Tell sinks to abort this txn id
            self._router.emit(
                "panels_txn_abort",
                level="info",
                scope="panel",
                data=None,
                extra={"_txn_action": "abort", "_txn_id": self._txn_id},
            )
            self._active = False
        def __exit__(self, exc_type, exc, tb) -> None:
            if exc_type is None:
                self.commit()
                # Fallback verification: if staging directory still exists (commit failed silently), attempt direct copy
                try:
                    base_dir = _env_get_str('G6_PANELS_DIR', os.path.join('data','panels'))
                    stage_dir = os.path.join(base_dir, '.txn', self._txn_id)
                    if os.path.isdir(stage_dir):
                        for name in os.listdir(stage_dir):
                            if name.endswith('.json'):
                                src = os.path.join(stage_dir, name)
                                dst = os.path.join(base_dir, name)
                                try:
                                    os.makedirs(base_dir, exist_ok=True)
                                    with open(src,encoding='utf-8') as _rf, open(dst,'w',encoding='utf-8') as _wf:
                                        _wf.write(_rf.read())
                                except Exception:
                                    pass
                        # Attempt meta write if primary loop panel present
                        try:
                            meta_path = os.path.join(base_dir, '.meta.json')
                            if not os.path.exists(meta_path):
                                meta_payload = {"last_txn_id": self._txn_id, "committed_at": OutputEvent.now_iso(), "panels": [p[:-5] for p in os.listdir(stage_dir) if p.endswith('.json')]}
                                with open(meta_path,'w',encoding='utf-8') as _mf:
                                    json.dump(meta_payload, _mf)
                        except Exception:
                            pass
                        # Aggressive cleanup of individual txn dir and prune root if empty
                        try:
                            import shutil as _sh
                            import time as _t
                            _sh.rmtree(stage_dir, ignore_errors=True)
                            if os.path.isdir(stage_dir):  # retry briefly
                                _t.sleep(0.05)
                                _sh.rmtree(stage_dir, ignore_errors=True)
                            root_dir = os.path.join(base_dir, '.txn')
                            if os.path.isdir(root_dir) and not os.listdir(root_dir):
                                _sh.rmtree(root_dir, ignore_errors=True)
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                self.abort()
                # Abort fallback cleanup if directory persists
                try:
                    base_dir = _env_get_str('G6_PANELS_DIR', os.path.join('data','panels'))
                    stage_dir = os.path.join(base_dir, '.txn', self._txn_id)
                    if os.path.isdir(stage_dir):
                        import shutil as _sh
                        import time as _t
                        _sh.rmtree(stage_dir, ignore_errors=True)
                        if os.path.isdir(stage_dir):
                            _t.sleep(0.05)
                            _sh.rmtree(stage_dir, ignore_errors=True)
                    root_dir = os.path.join(base_dir, '.txn')
                    if os.path.isdir(root_dir) and not os.listdir(root_dir):
                        import shutil as _sh
                        _sh.rmtree(root_dir, ignore_errors=True)
                except Exception:
                    pass

    def begin_panels_txn(self, txn_id: str | None = None) -> OutputRouter.PanelsTransaction:
        """Begin a panels transaction. Use as a context manager:
        with router.begin_panels_txn():
            router.panel_update(...)
            ...
        """
        return OutputRouter.PanelsTransaction(self, txn_id)

    def close(self) -> None:  # pragma: no cover - cleanup helper for tests
        # Give sinks a chance to cleanup
        for s in self._sinks:
            try:
                if hasattr(s, 'close'):
                    s.close()
            except Exception:
                pass
        self._sinks.clear()
        self._panel_txn_stack.clear()


# ------------------------------
# Factory / singleton
# ------------------------------

_router_singleton: OutputRouter | None = None


def _build_from_env() -> OutputRouter:
    sinks_env = _env_get_str("G6_OUTPUT_SINKS", "stdout,logging").strip()
    min_level = _env_get_str("G6_OUTPUT_LEVEL", "info").strip().lower() or "info"
    sinks: list[OutputSink] = []

    for token in [s.strip().lower() for s in sinks_env.split(",") if s.strip()]:
        if token == "stdout":
            sinks.append(StdoutSink())
        elif token == "logging":
            sinks.append(LoggingSink())
        elif token == "rich":
            if _rich_console is not None:
                sinks.append(RichSink())
        elif token == "jsonl":
            path = _env_get_str("G6_OUTPUT_JSONL_PATH", "g6_output.jsonl")
            sinks.append(JsonlSink(path))
        elif token == "memory":
            sinks.append(MemorySink())
        elif token == "panels":
            base_dir = _env_get_str("G6_PANELS_DIR", os.path.join("data", "panels"))
            include = _env_get_str("G6_PANELS_INCLUDE", "").strip()
            include_set = [s for s in include.split(",") if s.strip()] if include else None
            atomic = _env_get_bool("G6_PANELS_ATOMIC", True)
            sinks.append(PanelFileSink(base_dir, include=include_set, atomic=atomic))
        # Unknown tokens are ignored to be forgiving

    if not sinks:
        # Always have at least a stdout sink
        sinks.append(StdoutSink())
    # Install colorizing filter (safe no-op if mode disabled or Rich active)
    try:
        _install_color_filter()
    except Exception:
        pass
    return OutputRouter(sinks=sinks, min_level=min_level)


def get_output(reset: bool = False) -> OutputRouter:
    global _router_singleton
    if reset or _router_singleton is None:
        if _router_singleton is not None and reset:
            try:
                _router_singleton.close()
            except Exception:
                pass
        _router_singleton = _build_from_env()
    return _router_singleton
