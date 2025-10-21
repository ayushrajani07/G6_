"""Process-wide root detection cache (R4 optimization).

Provides cached wrapper around symbol_root.detect_root to avoid repeated root
scans over large option universes. Keeps implementation lightweight and
failure-tolerant. Optional disable via G6_DISABLE_ROOT_CACHE=1.
"""
from __future__ import annotations

import os
from threading import RLock

try:
    from src.utils.symbol_root import detect_root as _detect_root  # type: ignore
except Exception:  # pragma: no cover
    def _detect_root(s: str) -> str | None:  # type: ignore
        return None

# Use centralized env adapter with safe fallbacks to avoid import cycles during early init
try:
    from src.collectors.env_adapter import get_str as _env_get_str  # type: ignore
except Exception:  # pragma: no cover
    def _env_get_str(name: str, default: str = "") -> str:
        try:
            v = os.getenv(name)
            return default if v is None else v
        except Exception:
            return default

def _as_bool(val: str) -> bool:
    v = (val or "").strip().lower()
    return v in ("1", "true", "yes", "on")

def _as_int(val: str, default: int) -> int:
    try:
        return int(val)
    except Exception:
        return default

_DISABLE = _as_bool(_env_get_str('G6_DISABLE_ROOT_CACHE', '0'))
_MAX = _as_int(_env_get_str('G6_ROOT_CACHE_MAX', '4096'), 4096)

_CACHE: dict[str,str] = {}
_HITS = 0
_MISSES = 0
_EVICTIONS = 0
_lock = RLock()

__all__ = ["cached_detect_root","cache_stats","clear_root_cache"]


def cached_detect_root(ts: str) -> str | None:
    if not ts:
        return None
    if _DISABLE:
        return _detect_root(ts)
    key = ts.upper().strip()
    global _HITS, _MISSES
    with _lock:
        if key in _CACHE:
            _HITS += 1
            _update_metrics(hit=True)
            return _CACHE[key] or None
    root = _detect_root(key) or ''
    with _lock:
        if key not in _CACHE:
            # Trivial size bound eviction (FIFO-ish): pop arbitrary 5% when exceeding max
            if len(_CACHE) >= _MAX:
                # remove ~5% oldest by iteration (dict preserves insertion order in Py3.7+)
                drop = max(1, _MAX // 20)
                removed = 0
                for k in list(_CACHE.keys())[:drop]:
                    if _CACHE.pop(k, None) is not None:
                        removed += 1
                if removed:
                    global _EVICTIONS
                    _EVICTIONS += removed
                    _update_metrics(evicted=removed)
            _CACHE[key] = root
            _MISSES += 1
            _update_metrics(hit=False)
    return root or None


def cache_stats() -> dict:
    with _lock:
        return {
            "size": len(_CACHE),
            "hits": _HITS,
            "misses": _MISSES,
            "evictions": _EVICTIONS,
            "hit_ratio": (_HITS / (_HITS + _MISSES)) if (_HITS + _MISSES) else None,
            "capacity": _MAX,
            "enabled": not _DISABLE,
        }


def clear_root_cache() -> None:
    with _lock:
        _CACHE.clear()
        global _HITS, _MISSES, _EVICTIONS
        _HITS = 0; _MISSES = 0; _EVICTIONS = 0
    _update_metrics()  # reflect cleared size/ratio


def _update_metrics(hit: bool | None = None, evicted: int = 0) -> None:  # pragma: no cover - exercised via public API
    """Push counters/gauges into metrics registry if available.

    Safe-noop if metrics subsystem absent or registration gated.
    """
    try:  # Lazy import to avoid circular dependency during early init
        from src.metrics import get_metrics  # facade import
    except Exception:
        return
    try:
        m = get_metrics()
    except Exception:
        return
    hits_c = getattr(m, 'root_cache_hits', None)
    misses_c = getattr(m, 'root_cache_misses', None)
    evict_c = getattr(m, 'root_cache_evictions', None)
    size_g = getattr(m, 'root_cache_size', None)
    ratio_g = getattr(m, 'root_cache_hit_ratio', None)
    try:
        if hit is True and hits_c:
            hits_c.inc()
        elif hit is False and misses_c:
            misses_c.inc()
        if evicted and evict_c:
            evict_c.inc(evicted)
        if size_g:
            size_g.set(len(_CACHE))
        if ratio_g:
            ratio = (_HITS / (_HITS + _MISSES)) if (_HITS + _MISSES) else 0.0
            ratio_g.set(ratio)
    except Exception:
        # Silent safety: metrics failures should never break trading path
        pass
