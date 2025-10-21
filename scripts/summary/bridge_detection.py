"""Helpers for detecting an already-running legacy panels bridge.

Used by unified loop to avoid double-writing panel JSON artifacts. The
heuristic intentionally favors *not* blocking (warn & disable PanelsWriter)
vs. terminating the unified loop.

Deprecation Reference:
    The legacy bridge (`scripts/status_to_panels.py`) is now an immediately
    blocked stub unless `G6_ALLOW_LEGACY_PANELS_BRIDGE=1` is set. This detection
    helper remains temporarily to avoid double-writing when users explicitly
    opt into the legacy path during short transitional windows.
"""
from __future__ import annotations

from pathlib import Path

import psutil  # type: ignore

_BRIDGE_TOKENS = {"status_to_panels.py", "scripts/status_to_panels.py"}

_DEF_SENTINEL = "panels_bridge.lock"

def panels_bridge_processes() -> list[int]:
    """Return PIDs that look like legacy panels bridge processes.

    Best-effort: parse process cmdline; ignore permission errors.
    """
    pids: list[int] = []
    for proc in psutil.process_iter(attrs=["pid", "cmdline"]):
        try:
            cmd = proc.info.get("cmdline") or []
            if any(tok in " ".join(cmd) for tok in _BRIDGE_TOKENS):
                pids.append(proc.info["pid"])  # type: ignore[index]
        except (psutil.NoSuchProcess, psutil.AccessDenied):  # pragma: no cover - race
            continue
    return pids

def sentinel_path(panels_dir: str, name: str = _DEF_SENTINEL) -> Path:
    return Path(panels_dir) / name

def create_sentinel(panels_dir: str) -> Path:
    sp = sentinel_path(panels_dir)
    try:
        sp.write_text("unified_loop_active\n", encoding="utf-8")
    except OSError:
        pass
    return sp

def legacy_bridge_active(panels_dir: str) -> tuple[bool, str]:
    """Detect if legacy bridge likely active.

    Returns (is_active, reason)
    """
    # 1. Running process heuristic
    pids = panels_bridge_processes()
    if pids:
        return True, f"detected process tokens (pids={pids})"
    # 2. Recent sentinel from legacy script (it might create later if we add it)
    sp = sentinel_path(panels_dir, "legacy_bridge.lock")
    try:
        if sp.exists() and (sp.stat().st_mtime > (Path.cwd().stat().st_mtime - 3600)):
            return True, "legacy sentinel present"
    except OSError:
        pass
    return False, "none"
