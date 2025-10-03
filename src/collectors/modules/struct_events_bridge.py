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
from typing import Any, Dict
import logging, json, os

logger = logging.getLogger(__name__)

_STRUCT_DISABLED = os.environ.get('G6_DISABLE_STRUCT_EVENTS','0').lower() in ('1','true','yes','on')

def emit_struct(event: str, fields: Dict[str, Any]) -> None:  # pragma: no cover (thin wrapper)
    if _STRUCT_DISABLED:
        return
    try:
        logger.info("STRUCT %s | %s", event, json.dumps(fields, default=str, ensure_ascii=False))
    except Exception:
        logger.debug("struct_emit_failed", exc_info=True)

def emit_strike_cluster(cluster_struct: Dict[str, Any]) -> None:  # pragma: no cover
    # event name fixed historically as 'strike_cluster'
    emit_struct('strike_cluster', cluster_struct)

__all__ = ["emit_struct", "emit_strike_cluster"]
