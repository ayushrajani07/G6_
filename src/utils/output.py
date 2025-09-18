from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Protocol, Sequence, Tuple, Union

# Optional Rich support
try:
    from rich.console import Console  # type: ignore
except Exception:  # pragma: no cover - absence of dependency is acceptable
    Console = None  # type: ignore


# ------------------------------
# Data model
# ------------------------------

JsonLike = Union[None, str, int, float, bool, Sequence["JsonLike"], Mapping[str, "JsonLike"]]


@dataclass
class OutputEvent:
    timestamp: str
    level: str
    message: str
    scope: Optional[str] = None
    tags: Optional[Union[List[str], Mapping[str, str]]] = None
    data: Optional[JsonLike] = None
    # Allow attaching arbitrary extras without breaking sinks
    extra: Optional[Mapping[str, Any]] = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        print(base, file=self._stream)


class LoggingSink:
    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
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


class RichSink:
    def __init__(self, console: Optional[Any] = None) -> None:
        self._console = console or (Console() if Console else None)

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
        self.events: List[OutputEvent] = []

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
    def __init__(self, base_dir: str, include: Optional[Iterable[str]] = None, atomic: bool = True) -> None:
        self._base_dir = base_dir
        self._include = {s.strip().lower() for s in include} if include else None
        self._atomic = bool(atomic)

    def _allowed(self, panel: str) -> bool:
        return True if self._include is None else (panel.lower() in self._include)

    @staticmethod
    def _atomic_replace(src_path: str, dst_path: str, retries: int = 20, delay: float = 0.05) -> None:
        import time as _time
        for _ in range(max(1, int(retries))):
            try:
                os.replace(src_path, dst_path)
                return
            except PermissionError:
                _time.sleep(delay)
            except OSError:
                _time.sleep(delay)
        # Last attempt (raise if fails)
        os.replace(src_path, dst_path)

    def emit(self, event: OutputEvent) -> None:
        # Only handle events produced by router.panel_update (extra has _panel)
        extra = event.extra or {}
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
        # Ensure base dir
        try:
            os.makedirs(self._base_dir, exist_ok=True)
        except Exception:
            pass
        dst = os.path.join(self._base_dir, f"{panel_s}.json")
        tmp = dst + ".tmp"
        try:
            # Load previous for append/extend
            prev_data = None
            if mode in ("append", "extend") and os.path.exists(dst):
                try:
                    with open(dst, "r", encoding="utf-8") as rf:
                        prev_obj = json.load(rf)
                    prev_data = prev_obj.get("data") if isinstance(prev_obj, dict) else None
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

            payload = {
                "panel": panel_s,
                "updated_at": event.timestamp,
                "kind": extra.get("_kind"),
                "data": new_data,
            }

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
                os.replace(tmp, dst)
        except Exception:
            # Swallow sink exceptions
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
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
    def __init__(self, sinks: Optional[List[OutputSink]] = None, min_level: str = "info") -> None:
        self._sinks: List[OutputSink] = list(sinks or [])
        self._min_level = _normalize_level(min_level)

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
        scope: Optional[str] = None,
        tags: Optional[Union[List[str], Mapping[str, str]]] = None,
        data: Optional[JsonLike] = None,
        extra: Optional[Mapping[str, Any]] = None,
        timestamp: Optional[str] = None,
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
    def panel_update(self, panel: str, data: JsonLike, *, kind: Optional[str] = None) -> None:
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_update:{panel}",
            scope="panel",
            tags=None,
            data=data,
            extra={"_panel": panel, "_kind": kind} if kind else {"_panel": panel},
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

    def panel_append(self, panel: str, item: JsonLike, *, cap: int = 100, kind: Optional[str] = None) -> None:
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_append:{panel}",
            scope="panel",
            tags=None,
            data=item,
            extra={"_panel": panel, "_kind": kind, "_mode": "append", "_cap": cap} if kind else {"_panel": panel, "_mode": "append", "_cap": cap},
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                try:
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)
                except Exception:
                    pass

    def panel_extend(self, panel: str, items: Sequence[JsonLike], *, cap: int = 100, kind: Optional[str] = None) -> None:
        evt = OutputEvent(
            timestamp=OutputEvent.now_iso(),
            level="info",
            message=f"panel_extend:{panel}",
            scope="panel",
            tags=None,
            data=list(items),
            extra={"_panel": panel, "_kind": kind, "_mode": "extend", "_cap": cap} if kind else {"_panel": panel, "_mode": "extend", "_cap": cap},
        )
        for s in self._sinks:
            try:
                s.emit(evt)
            except Exception:
                try:
                    logging.getLogger("g6").exception("Output sink failed: %s", type(s).__name__)
                except Exception:
                    pass


# ------------------------------
# Factory / singleton
# ------------------------------

_router_singleton: Optional[OutputRouter] = None


def _build_from_env() -> OutputRouter:
    sinks_env = os.getenv("G6_OUTPUT_SINKS", "stdout,logging").strip()
    min_level = os.getenv("G6_OUTPUT_LEVEL", "info").strip().lower() or "info"
    sinks: List[OutputSink] = []

    for token in [s.strip().lower() for s in sinks_env.split(",") if s.strip()]:
        if token == "stdout":
            sinks.append(StdoutSink())
        elif token == "logging":
            sinks.append(LoggingSink())
        elif token == "rich":
            if Console:
                sinks.append(RichSink())
        elif token == "jsonl":
            path = os.getenv("G6_OUTPUT_JSONL_PATH", "g6_output.jsonl")
            sinks.append(JsonlSink(path))
        elif token == "memory":
            sinks.append(MemorySink())
        elif token == "panels":
            base_dir = os.getenv("G6_PANELS_DIR", os.path.join("data", "panels"))
            include = os.getenv("G6_PANELS_INCLUDE", "").strip()
            include_set = [s for s in include.split(",") if s.strip()] if include else None
            atomic = os.getenv("G6_PANELS_ATOMIC", "true").strip().lower() in ("1", "true", "yes", "on")
            sinks.append(PanelFileSink(base_dir, include=include_set, atomic=atomic))
        # Unknown tokens are ignored to be forgiving

    if not sinks:
        # Always have at least a stdout sink
        sinks.append(StdoutSink())

    return OutputRouter(sinks=sinks, min_level=min_level)


def get_output(reset: bool = False) -> OutputRouter:
    global _router_singleton
    if reset or _router_singleton is None:
        _router_singleton = _build_from_env()
    return _router_singleton
