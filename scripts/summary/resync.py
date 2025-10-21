"""Resync snapshot helpers.

Provides get_resync_snapshot used by HTTP handlers to materialize a JSON payload.
"""
from __future__ import annotations

from typing import Any


def get_resync_snapshot(
    status: dict[str, Any] | None = None,
    *,
    cycle: int = 0,
    domain: Any = None,
    reuse_hashes: Any = None,
) -> dict[str, Any]:
    """Build a minimal resync snapshot payload.

    Contract expected by tests:
      - Include "cycle" as int
      - Include "panels" mapping where each key has at least a {"hash": <str>} entry
      - Prefer hashes provided via ``reuse_hashes`` argument (e.g. from SSE full snapshot
        or SummarySnapshot.panel_hashes). If not provided, fall back to any shared hashes
        present under status.panel_push_meta.shared_hashes.
    """
    panels: dict[str, Any] = {}

    # Priority 1: explicit reuse_hashes (e.g., from SSEPublisher or snapshot.panel_hashes)
    try:
        if isinstance(reuse_hashes, dict) and reuse_hashes:
            panels = {str(k): {"hash": v} for k, v in reuse_hashes.items()}
    except Exception:
        panels = {}

    # Priority 2: shared hashes embedded in status (if panels still empty)
    if not panels:
        try:
            if isinstance(status, dict):
                meta = status.get('panel_push_meta') or {}
                if isinstance(meta, dict):
                    shared_hashes = meta.get('shared_hashes')
                    if isinstance(shared_hashes, dict):
                        # If provided as {key: hash}, normalize to {key: {hash: value}}
                        # or if already nested, keep as-is
                        normalized: dict[str, Any] = {}
                        for k, v in shared_hashes.items():
                            if isinstance(v, dict) and 'hash' in v:
                                normalized[str(k)] = v
                            else:
                                normalized[str(k)] = {"hash": v}
                        panels = normalized
        except Exception:
            panels = {}

    return {
        'cycle': int(cycle or 0),
        'panels': panels,
    }


__all__ = ["get_resync_snapshot"]
