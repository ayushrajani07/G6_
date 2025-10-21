"""Thread-safe in-memory cache for latest ExpirySnapshot objects.

Enabled when env G6_SNAPSHOT_CACHE=1 (writer side) and served via HTTP /snapshots
route (see catalog_http extension). Designed to avoid repeated reconstruction of
snapshot objects while allowing lightweight JSON serialization.
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # only for type checking; at runtime avoid import cost / cycles
    from .models import ExpirySnapshot  # noqa: F401

# Use 'Any' for runtime containers; we only depend on duck-typed 'as_dict'
ExpirySnapshot = Any  # type: ignore

_LOCK = threading.RLock()
# map (index, expiry_rule) -> ExpirySnapshot
_SNAPSHOTS: dict[tuple[str, str], Any] = {}
_LAST_UPDATED: dt.datetime | None = None


def enabled() -> bool:
    return os.environ.get('G6_SNAPSHOT_CACHE','').lower() in ('1','true','yes','on')


def update(snapshots: Iterable[Any]) -> None:
    """Insert/refresh snapshots (dashboard HTTP currently disabled)."""
    global _LAST_UPDATED
    with _LOCK:
        for snap in snapshots:
            key = (snap.index, snap.expiry_rule)
            _SNAPSHOTS[key] = snap
    _LAST_UPDATED = dt.datetime.now(dt.UTC)


def get_all(index: str | None = None) -> list[Any]:
    with _LOCK:
        if index is None:
            return list(_SNAPSHOTS.values())
        return [s for (idx, _), s in _SNAPSHOTS.items() if idx == index]

def clear() -> None:
    """Clear all cached snapshots (test utility)."""
    global _LAST_UPDATED
    with _LOCK:
        _SNAPSHOTS.clear()
    _LAST_UPDATED = None


def serialize(index: str | None = None) -> dict[str, object]:  # SerializedSnapshotsDict at runtime
    snaps = get_all(index)
    # to avoid import cycle, rely on snapshot having as_dict method (added via models patch)
    data = [s.as_dict() if hasattr(s, 'as_dict') else str(s) for s in snaps]
    overview = None
    try:
        from .models import OverviewSnapshot  # type: ignore
        if snaps:
            overview = OverviewSnapshot.from_expiry_snapshots(snaps).as_dict()
    except Exception:
        overview = None
    return {
        'generated_at': (_LAST_UPDATED or dt.datetime.now(dt.UTC)).isoformat().replace('+00:00','Z'),
        'count': len(data),
        'snapshots': data,
        'overview': overview,
    }

__all__ = ['update', 'get_all', 'serialize', 'enabled', 'clear']
