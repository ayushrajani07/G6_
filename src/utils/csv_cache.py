"""Simple mtime-based cache for CSV/JSON reads.

This module centralizes small file read patterns used widely across the repo.
It caches by file modification time, avoiding repeated disk I/O when files are
polled frequently (e.g., live/overview CSVs and runtime status JSON).

API
- get_last_row_csv(path: Path) -> Optional[Dict[str,str]]
- read_json_cached(path: Path) -> Any

Notes
- Safe for multi-caller usage within a single process.
- On any read error, returns None/{} rather than raising.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

_last_row_cache: dict[Path, tuple[float, dict[str, str] | None]] = {}
_json_cache: dict[Path, tuple[float, Any]] = {}


def get_last_row_csv(path: Path) -> dict[str, str] | None:
    """Return the last row of a CSV file as a dict, cached by file mtime."""
    try:
        if not path.exists():
            return None
        st = path.stat()
        mtime = getattr(st, 'st_mtime_ns', None) or st.st_mtime
        cached = _last_row_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        last: dict[str, str] | None = None
        with path.open("r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                last = row
        _last_row_cache[path] = (mtime, last)
        return last
    except Exception:
        return None


def read_json_cached(path: Path) -> Any:
    """Return parsed JSON from file, cached by file mtime."""
    try:
        if not path.exists():
            return {}
        st = path.stat()
        mtime = getattr(st, 'st_mtime_ns', None) or st.st_mtime
        cached = _json_cache.get(path)
        if cached and cached[0] == mtime:
            return cached[1]
        data = json.loads(path.read_text(encoding="utf-8"))
        _json_cache[path] = (mtime, data)
        return data
    except Exception:
        return {}


__all__ = ["get_last_row_csv", "read_json_cached"]
