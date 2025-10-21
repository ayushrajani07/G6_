"""Bridge module consolidating ad-hoc STRUCT event emissions.

Purpose: unify inline generic STRUCT logger usages inside `unified_collectors` with
existing helpers in `helpers.struct_events`. We provide two entrypoints:

    emit_struct(event: str, fields: dict) -> None
    emit_strike_cluster(cluster_struct: dict) -> None

Behavior: identical formatting ("STRUCT <event> | <json>") and honors the
G6_DISABLE_STRUCT_EVENTS environment flag just like helpers.struct_events.

This avoids keeping a private inline function in the monolithic collector file,
supporting future centralization (e.g., routing to alternate sinks).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_STRUCT_DISABLED = os.environ.get('G6_DISABLE_STRUCT_EVENTS','0').lower() in ('1','true','yes','on')

# Optional fine-grained suppression: comma/space separated event names.
_SUPPRESS_EVENTS: set[str] = set()
try:
    _raw = os.environ.get('G6_STRUCT_EVENTS_SUPPRESS','')
    if _raw:
        for tok in _raw.replace(',', ' ').split():
            _SUPPRESS_EVENTS.add(tok.strip())
except Exception:  # pragma: no cover
    pass

def emit_struct(event: str, fields: dict[str, Any]) -> None:  # pragma: no cover (thin wrapper)
    if _STRUCT_DISABLED:
        return
    if event in _SUPPRESS_EVENTS:
        return
    try:
        logger.info("STRUCT %s | %s", event, json.dumps(fields, default=str, ensure_ascii=False))
    except Exception:
        logger.debug("struct_emit_failed", exc_info=True)

def emit_strike_cluster(cluster_struct: dict[str, Any]) -> None:  # pragma: no cover
    # event name fixed historically as 'strike_cluster'
    emit_struct('strike_cluster', cluster_struct)

__all__ = ["emit_struct", "emit_strike_cluster"]
