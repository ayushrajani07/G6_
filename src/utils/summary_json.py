"""JSON emission helpers for one-shot startup summaries.

Provides a single function `emit_summary_json` that wraps json.dumps with
masking of sensitive-looking keys and stable field ordering (by key).

Environment flags (per subsystem) decide whether JSON variants are emitted.
The caller passes a `summary_type` (e.g., 'settings', 'provider', 'metrics', 'orchestrator').

Masking rules (simple regex heuristics): any key containing one of:
    token, secret, password, key (case-insensitive) -> value replaced with '***'.

Fields with value None are retained for explicitness.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from collections.abc import Iterable, Mapping
from typing import Any

_SENSITIVE_PATTERN = re.compile(r"(token|secret|password|apikey|api_key|key)", re.IGNORECASE)

logger = logging.getLogger(__name__)

def _mask_key(k: str, v: Any) -> Any:
    try:
        if _SENSITIVE_PATTERN.search(k):
            if v in (None, ''):
                return v
            return '***'
    except Exception:
        pass
    return v

def emit_summary_json(summary_type: str, fields: Mapping[str, Any] | Iterable[tuple[str, Any]], *, logger_override=None) -> None:
    log = logger_override or logger
    start = time.time()
    try:
        if isinstance(fields, dict):
            items = list(fields.items())
        else:
            items = list(fields)
    except Exception:
        items = []
    masked = {str(k): _mask_key(str(k), v) for k,v in items}
    ordered = {k: masked[k] for k in sorted(masked.keys())}
    h = hashlib.sha256(('|'.join(f"{k}={ordered[k]}" for k in ordered)).encode('utf-8')).hexdigest()[:16]
    payload = {
        'type': f'{summary_type}.summary.json',
        'ts': int(time.time()),
        'fields': ordered,
        'hash': h,
        'emit_ms': round((time.time() - start)*1000.0, 3),
    }
    try:
        log.info("%s", json.dumps(payload, separators=(',',':'), sort_keys=False))
    except Exception:
        pass
    # Forward hash to dispatcher (best-effort)
    try:
        from src.observability.startup_summaries import note_json_hash  # type: ignore
        note_json_hash(h)
    except Exception:
        pass

__all__ = ['emit_summary_json']
