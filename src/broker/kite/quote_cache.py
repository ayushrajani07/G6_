"""Quote cache (A7 Step 8 extraction).

Thread-safe in-memory cache storing raw quote payloads keyed by symbol.
Previously inline in quotes.py; extracted to enable future alternative backends.
"""
from __future__ import annotations

import threading
import time

try:  # local import guard to avoid hard dependency when metrics disabled
    from src.metrics import get_metrics  # type: ignore
except Exception:  # pragma: no cover
    def get_metrics():  # type: ignore
        return None

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, dict]] = {}
_HITS = 0
_MISSES = 0

def _export_metrics(hit: bool | None) -> None:
    m = get_metrics()
    if not m:
        return
    try:
        # Lazily allocate metrics if missing (registered via spec MetricDef on init; fall back if absent)
        # We only SET gauges if they exist; we do not create if absent to avoid duplicate registration risk.
        if hit is True and hasattr(m, 'quote_cache_hits'):
            try: m.quote_cache_hits.inc()  # type: ignore[attr-defined]
            except Exception: pass
        elif hit is False and hasattr(m, 'quote_cache_misses'):
            try: m.quote_cache_misses.inc()  # type: ignore[attr-defined]
            except Exception: pass
        total = _HITS + _MISSES
        if hasattr(m, 'quote_cache_size'):
            try: m.quote_cache_size.set(len(_CACHE))  # type: ignore[attr-defined]
            except Exception: pass
        if total and hasattr(m, 'quote_cache_hit_ratio'):
            try: m.quote_cache_hit_ratio.set(_HITS / total)  # type: ignore[attr-defined]
            except Exception: pass
    except Exception:
        pass

def get(symbol: str, ttl: float) -> dict | None:
    global _HITS, _MISSES  # noqa: PLW0603
    if ttl <= 0:
        _MISSES += 1
        _export_metrics(hit=False)
        return None
    now = time.time()
    with _LOCK:
        entry = _CACHE.get(symbol)
        if not entry:
            _MISSES += 1
            _export_metrics(hit=False)
            return None
        ts, data = entry
        if (now - ts) <= ttl:
            _HITS += 1
            _export_metrics(hit=True)
            return data
        _MISSES += 1
        _export_metrics(hit=False)
        return None

def put(raw: dict, ttl: float) -> None:
    if ttl <= 0 or not isinstance(raw, dict):
        return
    now = time.time()
    with _LOCK:
        for k, v in raw.items():
            if isinstance(v, dict):
                _CACHE[k] = (now, v)
    # Update size & ratio gauges (hit parameter None indicates no change to hit/miss counters just size update)
    _export_metrics(hit=None)

def snapshot_meta() -> dict:
    with _LOCK:
        return {'size': len(_CACHE), 'hits': _HITS, 'misses': _MISSES}

def reset_counters() -> None:  # test helper
    global _HITS, _MISSES  # noqa: PLW0603
    with _LOCK:
        _HITS = 0
        _MISSES = 0

__all__ = ['get', 'put', 'snapshot_meta', 'reset_counters']
