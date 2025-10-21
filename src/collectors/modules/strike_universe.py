"""Phase 9: Strike Universe Abstraction

Unified, policy & cache backed strike universe builder.

Motivation
----------
Historically strike lists were produced in multiple places:
  * utils.strikes.build_strikes (canonical deterministic builder)
  * unified_collectors inline / fallback wrappers
  * index_processor (adaptive scaling + local fallback)
  * strike_depth.compute_strike_universe (thin wrapper)

This module becomes the single orchestration surface for generating the
"strike universe" (ordered list of strikes + diagnostic metadata) so that:
  * Adaptive depth scaling, policy based step sizing, and per-index overrides
    are centrally applied.
  * Caching / de-duplication prevents recomputing identical strike lists
    within a cycle (hot path for multi-expiry processing and parity harness).
  * Meta diagnostics are standardized for future parity signature inclusion
    (e.g. step, cache_hit, policy, itm/otm, scale_applied).

High Level Contract
-------------------
Function: build_strike_universe(atm, n_itm, n_otm, index_symbol, *,
                                scale=None, step=None, policy=None,
                                cache=True, metrics=None) -> StrikeUniverseResult

Inputs:
  atm: float  (normalized at-the-money strike; <=0 -> empty universe)
  n_itm/n_otm: depth counts (pre-adaptive)
  index_symbol: e.g. NIFTY, BANKNIFTY
  scale: optional multiplicative factor (already computed by adaptive/memory logic)
  step: explicit step override (bypasses policy + env overrides if provided)
  policy: optional object/function providing compute_step(index_symbol, atm)->float
  cache: bool flag or explicit cache object implementing get/set
  metrics: optional metrics facade (best effort non-fatal)

Output:
  StrikeUniverseResult(strikes: list[float], meta: dict[str, Any]) where meta keys are:
    - count
    - atm
    - itm
    - otm
    - scale_applied
    - step
    - policy (policy name or 'default')
    - cache_hit (bool)
    - cache_key (hashable tuple repr)  [for debugging]
    - source (always 'strike_universe_v1')

Caching Strategy
----------------
Keyed by: (index_symbol, step_resolved, round(atm/step_resolved), itm_scaled, otm_scaled, scale_applied)
Rationale: Minor ATM fluctuations inside one step bucket produce the same ladder.

LRU size: configurable via env G6_STRIKE_UNIVERSE_CACHE_SIZE (default 256). Disable
with env G6_DISABLE_STRIKE_CACHE=1 (or passing cache=False).

Policy Resolution Order
-----------------------
1. If explicit step provided -> use as-is.
2. Environment override G6_STRIKE_STEP_<INDEX>
3. Policy (if provided and returns >0)
4. Index registry meta step (utils.index_registry.get_index_meta)
5. Fallback heuristic: 100 for BANKNIFTY/SENSEX else 50.

Thread Safety
-------------
A simple OrderedDict based LRU is used; for the current synchronous call sites
this is sufficient. If future async/threaded enrichment uses this module
concurrently we can wrap mutations with a lightweight lock.

Future Extensions
-----------------
* Vectorized batch builder for multiple ATMs (performance micro-opt)
* Multi-tier step sizing (adjust step if ATM magnitude crosses thresholds)
* Adaptive depth policy hooks (expose chosen scale factor & reasons)
* Observability: emit structured event when cache first grows beyond N

Parity Considerations
---------------------
This module deliberately delegates numeric strike generation to
utils.strikes.build_strikes to avoid divergence. Only meta & caching are new.

"""
from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Protocol

try:  # canonical generator (Phase 2 centralization)
    # Import may fail in stripped-down environments (tests / minimal builds).
    from src.utils.strikes import build_strikes as _base_build_strikes  # pragma: no cover
except Exception:  # pragma: no cover
    _base_build_strikes = None  # fallback placeholder

__all__ = [
    "StrikeUniverseResult",
    "StrikeStepPolicy",
    "build_strike_universe",
    "get_cache_diagnostics",
]


class StrikeStepPolicy(Protocol):  # pragma: no cover - interface only
    def compute_step(self, index_symbol: str, atm: float) -> float:  # noqa: D401
        """Return desired step size for given index & atm (>0).

        Implementations must return a positive float. This Protocol
        supplies only the signature for static type checking.
        """
        ...


@dataclass
class StrikeUniverseResult:
    strikes: list[float]
    meta: dict


# ------------------------ internal cache implementation ---------------------
class _LRUStrikeCache:
    def __init__(self, capacity: int = 256) -> None:
        self.capacity = max(16, capacity)
        self._data: OrderedDict[tuple[Any, ...], list[float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[Any, ...]) -> list[float] | None:
        with self._lock:
            val = self._data.get(key)
            if val is not None:
                # move to end (LRU)
                self._data.move_to_end(key)
            return val

    def put(self, key: tuple[Any, ...], value: list[float]) -> None:
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self._data[key] = value
            else:
                self._data[key] = value
                if len(self._data) > self.capacity:
                    self._data.popitem(last=False)  # evict LRU

    def diagnostics(self) -> dict:
        with self._lock:
            return {
                "size": len(self._data),
                "capacity": self.capacity,
            }


# Singleton module-level cache (can be replaced / cleared in tests)
_CACHE_DISABLED = os.environ.get("G6_DISABLE_STRIKE_CACHE", "0").lower() in ("1", "true", "yes", "on")
_CACHE_CAPACITY = int(os.environ.get("G6_STRIKE_UNIVERSE_CACHE_SIZE", "256") or "256")
_STRIKE_CACHE: _LRUStrikeCache | None = None if _CACHE_DISABLED else _LRUStrikeCache(_CACHE_CAPACITY)


def _resolve_step(index_symbol: str, atm: float, explicit_step: float | None, policy: StrikeStepPolicy | None) -> tuple[float, str]:
    # 1. explicit
    if explicit_step is not None and explicit_step > 0:
        return float(explicit_step), "explicit"
    # 2. env override
    env_key = f"G6_STRIKE_STEP_{index_symbol.upper()}"
    try:
        if env_key in os.environ:
            v = float(os.environ[env_key])
            if v > 0:
                return v, "env"
    except Exception:
        pass
    # 3. policy
    if policy is not None:
        try:
            v = float(policy.compute_step(index_symbol, atm))
            if v > 0:
                return v, getattr(policy, "name", policy.__class__.__name__)
        except Exception:
            pass
    # 4. index registry
    try:
        from src.utils.index_registry import get_index_meta  # pragma: no cover
        v = float(get_index_meta(index_symbol).step)
        if v > 0:
            return v, "registry"
    except Exception:  # pragma: no cover - fallback path
        pass
    # 5. heuristic fallback
    return (100.0 if index_symbol.upper() in ("BANKNIFTY", "SENSEX") else 50.0), "heuristic"


def _apply_scale(itm: int, otm: int, scale: float | None) -> tuple[int, int]:
    if not scale or scale <= 0:
        return itm, otm
    _itm = max(1, int(round(itm * scale))) if itm > 0 else 0
    _otm = max(1, int(round(otm * scale))) if otm > 0 else 0
    return _itm, _otm


def build_strike_universe(
    atm: float,
    n_itm: int,
    n_otm: int,
    index_symbol: str,
    *,
    scale: float | None = None,
    step: float | None = None,
    policy: StrikeStepPolicy | None = None,
    cache: bool | _LRUStrikeCache = True,
    metrics: Any | None = None,
) -> StrikeUniverseResult:
    """Compute (or fetch from cache) the strike universe for an index snapshot.

    Returns a StrikeUniverseResult; strikes list is always ascending & unique.
    """
    if atm is None or atm <= 0:
        return StrikeUniverseResult([], {
            "count": 0,
            "atm": atm,
            "itm": n_itm,
            "otm": n_otm,
            "scale_applied": scale,
            "step": None,
            "policy": getattr(policy, "name", policy.__class__.__name__) if policy else None,
            "cache_hit": False,
            "cache_key": None,
            "source": "strike_universe_v1",
        })

    resolved_step, policy_name = _resolve_step(index_symbol, atm, step, policy)
    scaled_itm, scaled_otm = _apply_scale(int(n_itm or 0), int(n_otm or 0), scale)

    # Determine cache instance
    cache_inst: _LRUStrikeCache | None = None
    if cache and _STRIKE_CACHE is not None:
        cache_inst = _STRIKE_CACHE if cache is True else cache if isinstance(cache, _LRUStrikeCache) else None

    # Cache key uses bucketed ATM to avoid micro-diff duplication
    atm_bucket = int(round(atm / resolved_step)) if resolved_step > 0 else int(atm)
    cache_key = (index_symbol.upper(), resolved_step, atm_bucket, scaled_itm, scaled_otm, float(scale or 0.0))

    cache_hit = False
    if cache_inst is not None:
        cached = cache_inst.get(cache_key)
        if cached is not None:
            cache_hit = True
            strikes = cached
        else:
            strikes = _generate_strikes(atm, scaled_itm, scaled_otm, index_symbol, resolved_step)
            cache_inst.put(cache_key, strikes)
    else:
        strikes = _generate_strikes(atm, scaled_itm, scaled_otm, index_symbol, resolved_step)

    meta = {
        "count": len(strikes),
        "atm": atm,
        "itm": n_itm,
        "otm": n_otm,
        "scaled_itm": scaled_itm,
        "scaled_otm": scaled_otm,
        "scale_applied": scale,
        "step": resolved_step,
        "policy": policy_name,
        "cache_hit": cache_hit,
        "cache_key": cache_key if cache_hit else None,
        "source": "strike_universe_v1",
    }

    if metrics is not None:
        try:  # best-effort optional metrics hooks
            if cache_hit:
                inc_hits = getattr(metrics, "strike_universe_cache_hits", None)
                if inc_hits is not None:
                    try:
                        inc_hits.inc()
                    except Exception:
                        pass
            else:
                inc_miss = getattr(metrics, "strike_universe_cache_miss", None)
                if inc_miss is not None:
                    try:
                        inc_miss.inc()
                    except Exception:
                        pass
        except Exception:  # pragma: no cover
            pass

    return StrikeUniverseResult(strikes, meta)


def _generate_strikes(atm: float, itm: int, otm: int, index_symbol: str, step: float) -> list[float]:
    # Use canonical generator if present for parity.
    if _base_build_strikes is not None:
        # Defensive: upstream may return any iterable; coerce explicitly.
        try:
            res = _base_build_strikes(atm, itm, otm, index_symbol, step=step)
            return [float(x) for x in list(res)]
        except Exception:
            return []
    # Fallback simplified generation
    if atm <= 0:
        return []
    arr: list[float] = []
    for i in range(1, itm + 1):
        arr.append(float(atm - i * step))
    arr.append(float(atm))
    for i in range(1, otm + 1):
        arr.append(float(atm + i * step))
    return sorted(arr)


def get_cache_diagnostics() -> dict:
    if _STRIKE_CACHE is None:
        return {"enabled": False, "size": 0, "capacity": 0}
    return {"enabled": True, **_STRIKE_CACHE.diagnostics()}
