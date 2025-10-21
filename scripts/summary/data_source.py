from __future__ import annotations

import json
import os
import re
from typing import Any

from .env_config import load_summary_env

"""Panels data source helpers (auto-detect only).

Deprecated env vars `G6_SUMMARY_PANELS_MODE` / `G6_SUMMARY_READ_PANELS` fully purged.
Panels mode now strictly determined by presence/freshness of panel JSON files.
"""

def _auto_detect_panels(threshold_secs: float = 30.0) -> bool:
    """Heuristic: if panels dir exists and contains any recent *.json file, enable panels mode.

    A file is considered recent if modified within threshold_secs. If no mtimes can
    be read (permission errors), fall back to presence of at least one JSON.
    """
    panels_dir = _panels_dir()
    try:
        if not os.path.isdir(panels_dir):
            return False
        entries = [e for e in os.listdir(panels_dir) if e.endswith('.json')]
        if not entries:
            return False
        import time
        now = time.time()
        for name in entries:
            path = os.path.join(panels_dir, name)
            try:
                mtime = os.path.getmtime(path)
                if now - mtime <= threshold_secs:
                    return True
            except Exception:
                # Ignore and continue; if any readable file is found later we'll return True
                continue
        # No "recent" file; still treat as active panels source if at least one JSON exists
        return True
    except Exception:
        return False

# Panels JSON preference and readers

def detect_panels_mode() -> bool:
    return _auto_detect_panels()


def _use_panels_json() -> bool:  # backward compatibility internal name
    return detect_panels_mode()


def _panels_dir() -> str:
    # Centralized via SummaryEnv (panels_dir)
    try:
        val = load_summary_env().panels_dir
        return str(val)
    except Exception:
        return os.path.join("data", "panels")


def _read_json_with_retries(path: str, retries: int = 3, delay: float = 0.05) -> Any | None:
    """Read JSON file with small retry loop to avoid transient partial reads.

    This is a defensive reader-side safeguard. Writers already use atomic
    replace, but on some platforms readers can still see brief windows where
    open/parse fails. We keep this light to avoid masking real errors.
    """
    # First attempt: use centralized cached reader if available
    try:
        from pathlib import Path as _Path

        from src.utils.csv_cache import read_json_cached as _read_json_cached
        data = _read_json_cached(_Path(path))
        # Maintain previous semantics: return None on missing/empty to trigger retries if desired
        if data is not None:
            return data
    except Exception:
        pass
    for attempt in range(max(1, retries)):
        try:  # noqa: PERF203 - per-attempt isolation for transient read/parse failures
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:  # noqa: PERF203 - retry loop intentionally isolates per-attempt failures
            if attempt == retries - 1:
                break
            try:
                import time
                time.sleep(delay)
            except Exception:
                pass
    return None


def _read_panel_json(name: str) -> Any | None:
    if not _use_panels_json():
        return None
    # Use centralized unified data source for caching + change detection
    try:
        from src.data_access.unified_source import DataSourceConfig, UnifiedDataSource
        uds = UnifiedDataSource()
        cfg = DataSourceConfig(
            panels_dir=_panels_dir(),
            runtime_status_path=uds.config.runtime_status_path,
            metrics_url=uds.config.metrics_url,
            cache_ttl_seconds=uds.config.cache_ttl_seconds,
            watch_files=getattr(uds.config, 'watch_files', True),
            file_poll_interval=getattr(uds.config, 'file_poll_interval', 0.5),
        )
        uds.reconfigure(cfg)
        data = uds.get_panel_data(name)
        return data if data else None
    except Exception:
        # Fallback to local file read if unified source unavailable
        path = os.path.join(_panels_dir(), f"{name}.json")
        try:
            if not os.path.exists(path):
                return None
            obj = _read_json_with_retries(path)
            if obj is None:
                return None
            if isinstance(obj, dict) and "data" in obj:
                return obj.get("data")
            return obj
        except Exception:
            return None


# Log parsing support for indices metrics

def _tail_read(path: str, max_bytes: int = 65536) -> str | None:
    try:
        sz = os.path.getsize(path)
        with open(path, "rb") as f:
            if sz > max_bytes:
                f.seek(-max_bytes, os.SEEK_END)
            data = f.read()
        try:
            return data.decode("utf-8", errors="ignore")
        except Exception:
            return data.decode("latin-1", errors="ignore")
    except Exception:
        return None


def _parse_indices_metrics_from_text(text: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not text:
        return out
    pat = re.compile(
        r"(?P<idx>[A-Z]{3,10})\s+TOTAL\s+LEGS:\s+(?P<legs>\d+)"
        r"\s*\|\s*FAILS:\s+(?P<fails>\d+)\s*\|\s*STATUS:\s*(?P<status>[A-Z_]+)"
    )
    for m in pat.finditer(text):
        idx = m.group("idx").strip().upper()
        legs: int | None
        try:
            legs = int(m.group("legs"))
        except Exception:
            legs = None
        fails: int | None
        try:
            fails = int(m.group("fails"))
        except Exception:
            fails = None
        st = m.group("status").strip().upper()
        out[idx] = {"legs": legs, "fails": fails, "status": st}
    return out


def _get_indices_metrics_from_log() -> dict[str, dict[str, Any]]:
    try:
        cfg = load_summary_env()
        p = cfg.indices_panel_log
    except Exception:
        p = os.getenv("G6_INDICES_PANEL_LOG")  # last-resort fallback
    if p and os.path.exists(p):
        txt = _tail_read(p)
        if txt:
            return _parse_indices_metrics_from_text(txt)
    if os.path.exists("g6_platform.log"):
        txt = _tail_read("g6_platform.log")
        if txt:
            return _parse_indices_metrics_from_text(txt)
    return {}


def _get_indices_metrics() -> dict[str, dict[str, Any]]:
    # Prefer unified data source to eliminate duplicate path logic
    try:
        from src.data_access.unified_source import data_source
        data = data_source.get_indices_data()
        if isinstance(data, dict) and data:
            # Normalize to Dict[str, Dict[str, Any]]
            out: dict[str, dict[str, Any]] = {}
            for k, v in data.items():
                if isinstance(v, dict):
                    out[str(k)] = {**v}
            if out:
                return out
    except Exception:
        pass
    # Legacy fallback: panels JSON (when explicitly enabled) then logs
    if _use_panels_json():
        pj = _read_panel_json("indices")
        if isinstance(pj, dict) and pj:
            out2: dict[str, dict[str, Any]] = {}
            for k, v in pj.items():
                if isinstance(v, dict):
                    out2[str(k)] = {**v}
            if out2:
                return out2
    return _get_indices_metrics_from_log()
