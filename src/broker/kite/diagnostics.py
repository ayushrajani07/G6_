"""Diagnostics & health helpers (Phase A7 Step 3 extraction).

Contains logic originally housed on `KiteProvider`:
  * provider_diagnostics()
  * check_health()
  * synthetic quote usage helpers (implemented as pure helpers; provider maintains counters)

Provider contract expectations (kept minimal to avoid tight coupling):
  - Attributes: _state, _synthetic_quotes_used, _last_quotes_synthetic, _used_fallback
  - Methods: get_ltp([...])
  - Constants: INDEX_MAPPING (imported here), exposed via kite_provider

Behavioral parity: identical keys and fallback behavior; any exception returns empty dict
for diagnostics, or degraded/unhealthy for health check.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)

try:  # import mapping for health check pair selection
    from src.broker.kite_provider import INDEX_MAPPING as _INDEX_MAPPING  # type: ignore
    INDEX_MAPPING: dict[str, tuple[str, str]] = _INDEX_MAPPING
except Exception:  # pragma: no cover
    INDEX_MAPPING = {"NIFTY": ("NSE", "NIFTY 50")}


class _ProviderLike(Protocol):
    """Minimal protocol for provider used by diagnostics/health.

    We only rely on get_ltp for health; other attributes are accessed via
    getattr best-effort and therefore aren't part of the protocol surface.
    """

    def get_ltp(self, pairs: list[tuple[str, str]]) -> Any:
        ...


def provider_diagnostics(provider: _ProviderLike) -> dict[str, Any]:
    try:
        token_age_sec: float | None = None
        token_expiry: float | None = None
        cache_meta: dict[str, Any] = {}
        try:  # Attempt token metadata extraction (best effort)
            kc = getattr(provider, 'kite', None)
            issued = getattr(kc, 'api_token_issue_time', None)
            exp = getattr(kc, 'api_token_expiry', None)
            now_ts = time.time()
            if isinstance(issued, (int, float)):
                token_age_sec = max(0, now_ts - float(issued))
            if isinstance(exp, (int, float)):
                token_expiry = max(0, float(exp) - now_ts)
        except Exception:
            token_age_sec = None
            token_expiry = None
        # Quote cache meta (best-effort import)
        try:
            from src.broker.kite import quote_cache  # type: ignore
            cache_meta = quote_cache.snapshot_meta()
        except Exception:
            cache_meta = {}
        st = getattr(provider, '_state', None)
        return {
            'option_cache_size': len(getattr(st, 'option_instrument_cache', {})) if st else 0,
            'option_cache_hits': getattr(st, 'option_cache_hits', 0) if st else 0,
            'option_cache_misses': getattr(st, 'option_cache_misses', 0) if st else 0,
            'instruments_cached': {k: len(v or []) for k, v in getattr(st, 'instruments_cache', {}).items()} if st else {},
            'expiry_dates_cached': {k: len(v or []) for k, v in getattr(st, 'expiry_dates_cache', {}).items()} if st else {},
            'synthetic_quotes_used': int(getattr(provider, '_synthetic_quotes_used', 0)),
            'last_quotes_synthetic': bool(getattr(provider, '_last_quotes_synthetic', False)),
            'used_instrument_fallback': bool(getattr(provider, '_used_fallback', False)),
            'token_age_sec': token_age_sec,
            'token_time_to_expiry_sec': token_expiry,
            'quote_cache_size': cache_meta.get('size'),
            'quote_cache_hits': cache_meta.get('hits'),
            'quote_cache_misses': cache_meta.get('misses'),
        }
    except Exception:  # pragma: no cover
        return {}


def check_health(provider: _ProviderLike) -> dict[str, Any]:
    try:
        pair: tuple[str, str] = INDEX_MAPPING.get("NIFTY", ("NSE", "NIFTY 50"))
        ltp: Any = provider.get_ltp([pair])
        price_ok: bool = False
        if isinstance(ltp, dict):
            for v in ltp.values():
                if isinstance(v, dict) and isinstance(v.get('last_price'), (int, float)) and v['last_price'] > 0:
                    price_ok = True
                    break
        return {"status": "healthy" if price_ok else "degraded", "message": "Provider connected" if price_ok else "Invalid price"}
    except Exception as e:  # pragma: no cover
        msg = str(e).lower()
        if any(k in msg for k in ("token", "auth", "unauthor")):
            return {"status": "unhealthy", "message": "Auth/token issue detected"}
        return {"status": "unhealthy", "message": f"Health check failed: {e}"}


__all__ = [
    'provider_diagnostics',
    'check_health',
]
