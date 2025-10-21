"""Panel diff merge helper.

Pure helper to apply a diff event onto an existing in-memory panels mapping.

Diff Event Shape (convention):
{
  "panel": "provider",              # logical panel name (must match existing key in target or create new)
  "op": "diff" | "full",            # 'diff' means partial patch; 'full' means complete replacement
  "data": { ... }                     # new full payload or partial structure
}

Diff Semantics (op = 'diff'):
- For dict values: recursively merge keys.
  * If a value is exactly {"__remove__": true} remove that key from target (if present).
  * Otherwise replace leaf scalars/lists wholesale.
- For lists: list value replaces the existing list (no per-index merge) to keep semantics simple & predictable.
- For unknown types (None, int, float, str, bool): value replaces existing.

Full Semantics (op = 'full'):
- Replace the entire panel payload with event['data'].

Return: Updated new mapping (does not mutate original mapping in-place).
Raises: ValueError for malformed inputs (missing panel/op/data, wrong types).

This helper is intentionally side-effect free to support straightforward unit testing
and potential reuse by WebSocket / SSE ingestion code paths.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["merge_panel_diff"]

_REMOVE_SENTINEL = {"__remove__": True}


def _is_remove_sentinel(obj: Any) -> bool:
    return isinstance(obj, Mapping) and obj.get("__remove__") is True and len(obj) == 1


def _merge_dict(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = dict(base)  # shallow copy
    for k, v in patch.items():
        if _is_remove_sentinel(v):
            out.pop(k, None)
            continue
        if isinstance(v, Mapping) and isinstance(out.get(k), Mapping):
            out[k] = _merge_dict(out[k], v)  # type: ignore[arg-type]
        else:
            # Replace scalar / list / nested object entirely
            out[k] = v
    return out


def merge_panel_diff(existing_panels: Mapping[str, Any] | None, event: Mapping[str, Any]) -> dict[str, Any]:
    """Apply a panel diff/full event and return new panels mapping.

    existing_panels: current in-memory panels mapping (panel -> payload)
    event: dict with required keys: panel (str), op ('diff'|'full'), data (mapping or any JSON-serializable object)
    """
    if not isinstance(event, Mapping):
        raise ValueError("event must be a mapping")
    panel = event.get("panel")
    op = event.get("op")
    if not isinstance(panel, str) or not panel:
        raise ValueError("event.panel missing/invalid")
    if op not in {"diff", "full"}:
        raise ValueError("event.op must be 'diff' or 'full'")
    data = event.get("data")
    if op == "full":
        # Full replacement; data may be any JSON-serializable value
        new_panels = dict(existing_panels) if isinstance(existing_panels, Mapping) else {}
        new_panels[panel] = data
        return new_panels
    # diff op: data must be a mapping
    if not isinstance(data, Mapping):
        raise ValueError("diff op requires mapping payload in data")
    current_payload: dict[str, Any] = {}
    if isinstance(existing_panels, Mapping):
        cur = existing_panels.get(panel)
        if isinstance(cur, Mapping):
            current_payload = dict(cur)
    merged = _merge_dict(current_payload, data)
    new_panels = dict(existing_panels) if isinstance(existing_panels, Mapping) else {}
    new_panels[panel] = merged
    return new_panels
