from __future__ import annotations

"""Lightweight structured event emitter for pipeline observability.

Features:
- Guarded by env flags to avoid behavior changes and log volume when off.
- Emits compact single-line JSON on logger and optional stdout.
- Optional in-memory ring buffer stored on state.meta['struct_events'] for tests/smoke.

Env flags:
- G6_PIPELINE_STRUCT_EVENTS: enable/disable emission (default off)
- G6_PIPELINE_STRUCT_EVENTS_STDOUT: also print to stdout (default off)
- G6_PIPELINE_STRUCT_EVENTS_BUFFER: integer size of ring buffer; if >0 and state provided, keep last N events.
"""
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


def _truthy(v: str | None) -> bool:
    return v.lower() in ('1','true','yes','on','y') if isinstance(v, str) else False


def emit_struct_event(name: str, payload: dict[str, Any], *, state: Any | None = None) -> None:
    """Emit a structured event when enabled.

    Parameters:
      name: logical event name, e.g. 'expiry.phase.event' or 'expiry.snapshot.event'
      payload: JSON-serializable dict of attributes
      state: optional ExpiryState to append a ring-buffer under meta['struct_events']
    """
    try:
        if not _truthy(os.getenv('G6_PIPELINE_STRUCT_EVENTS','0')):
            return
        # Shallow copy and attach event name + timestamp
        evt = dict(payload or {})
        evt['event'] = name
        evt['ts'] = int(time.time())
        # Log compact JSON
        try:
            logger.debug('%s %s', name, json.dumps(evt, separators=(',',':'), sort_keys=True))
        except Exception:
            # Fallback repr
            logger.debug('%s %r', name, evt)
        if _truthy(os.getenv('G6_PIPELINE_STRUCT_EVENTS_STDOUT','0')):
            try:
                print(name, json.dumps(evt, separators=(',',':')))
            except Exception:
                pass
        # Optional in-memory buffer for tests / quick inspection
        try:
            buf_sz_raw = os.getenv('G6_PIPELINE_STRUCT_EVENTS_BUFFER', '')
            buf_sz = int(buf_sz_raw) if buf_sz_raw else 0
        except Exception:
            buf_sz = 0
        if state is not None and buf_sz > 0:
            try:
                meta = getattr(state, 'meta', None)
                if isinstance(meta, dict):
                    buf = meta.get('struct_events')
                    if not isinstance(buf, list):
                        buf = []
                        meta['struct_events'] = buf
                    buf.append(evt)
                    # prune head if exceeding buffer size
                    if len(buf) > buf_sz:
                        # keep last N
                        del buf[0:len(buf)-buf_sz]
            except Exception:
                pass
    except Exception:
        # Never raise from observability path
        pass


__all__ = ["emit_struct_event"]
