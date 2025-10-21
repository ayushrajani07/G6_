"""Client-side helpers to observe panel event end-to-end latency.

Intended to be imported by any consumer applying panel_full / panel_diff events.
If not imported, no latency histogram observations occur (zero overhead).
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

try:
    from src.metrics import get_metrics  # facade import
except Exception:  # pragma: no cover
    get_metrics = None  # type: ignore


def observe_event_latency(event_payload: Mapping[str, Any]) -> None:
    """Observe latency for a single panel event payload.

    Expects the raw event (already parsed JSON) structure as emitted over SSE:
      {
        'type': 'panel_diff'|'panel_full',
        'payload': {... '_generation': int, 'publish_unixtime': float ...},
        ...
      }
    If publish_unixtime missing or metrics not initialized, function is a no-op.
    """
    try:
        evt_type = event_payload.get('type')  # type: ignore[arg-type]
        if evt_type not in ('panel_full','panel_diff'):
            return
        payload = event_payload.get('payload')  # type: ignore[index]
        if not isinstance(payload, dict):
            return
        pub_ts = payload.get('publish_unixtime')
        if not isinstance(pub_ts, (int,float)):
            return
        now = time.time()
        latency = max(0.0, now - pub_ts)
        if get_metrics is None:
            return
        m = get_metrics()
        hist = getattr(m, 'panel_event_latency_seconds', None)
        if hist is not None:
            try:
                hist.labels(type=evt_type).observe(latency)
            except Exception:
                pass
    except Exception:
        # Silent fail: latency instrumentation is best-effort
        pass

__all__ = ["observe_event_latency"]
