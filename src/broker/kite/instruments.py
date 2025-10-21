"""Instruments fetch + cache module (extracted from kite_provider Phase A7 Step 1).

Responsibilities:
- Fetch full instrument universe via provider.kite.instruments()
- Maintain per-exchange cache with TTL + short backoff for empty lists
- Perform one-shot empty retry (as original logic) and diagnostic logging
- Mark provider _used_fallback flag when synthetic (empty) fallback engaged

Public entrypoint: fetch_instruments(provider, exchange: str, force_refresh: bool=False) -> list[dict]

Provider contract expectations (minimal to avoid tight coupling):
- provider._settings.instrument_cache_ttl (float seconds, default 600)
- provider._state.instruments_cache: dict[str, list]
- provider._state.instruments_cache_meta: dict[str, float]
- provider._ensure_client(): late client init
- provider._auth_failed flag
- provider.kite client with .instruments() method
- provider._api_rl optional rate limiter callable
- provider._rl_fallback() throttled logging helper returning bool
- provider._used_fallback flag (set True when returning synthetic empty result)

The module is intentionally dependency-light; it defers error classification
(auth vs other) to a local helper mirroring original heuristic to avoid
importing broader auth modules and increasing import cost.
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from src.error_handling import handle_provider_error  # type: ignore
from src.utils.retry import call_with_retry

logger = logging.getLogger(__name__)

if TYPE_CHECKING:  # pragma: no cover - hints only
    from src.broker.kite_provider import KiteProvider  # circular safe for typing


def _is_auth_error(e: BaseException) -> bool:
    msg = str(e).lower()
    return any(k in msg for k in ("auth", "token", "unauthorized", "forbidden", "expired"))


def fetch_instruments(provider: KiteProvider, exchange: str, force_refresh: bool = False) -> list[dict[str, Any]]:
    exch = exchange or "NFO"
    ttl = getattr(provider._settings, 'instrument_cache_ttl', 600.0)
    now = time.time()
    cached = provider._state.instruments_cache.get(exch)
    meta_ts = provider._state.instruments_cache_meta.get(exch, 0.0)
    if not force_refresh and cached is not None and (now - meta_ts) < ttl:
        # If cached is empty, expire it faster so we retry soon
        if cached:
            return cached
        if (now - meta_ts) < 5.0:  # within short retry window keep returning to avoid hammering
            return cached
        # else fall through to refresh
    elif force_refresh:
        logger.debug("force_refresh_instruments exch=%s", exch)

    provider._ensure_client()
    try:
        if provider._auth_failed:
            raise RuntimeError("kite_auth_failed")
        if provider.kite is None:
            raise RuntimeError("kite_client_unavailable")

        def _fetch():
            if provider._api_rl:
                provider._api_rl()
            from src.broker.kite_provider import _timed_call  # local import to avoid cycle at module import
            timeout = getattr(provider._settings, 'kite_instruments_timeout_sec', None) or getattr(provider._settings, 'kite_timeout_sec', 5.0)
            return _timed_call(lambda: provider.kite.instruments(), timeout)  # type: ignore[arg-type]

        raw = call_with_retry(_fetch)
        if isinstance(raw, list) and not raw:
            logger.warning("instrument_fetch_returned_empty_list exch=%s", exch)
            try:
                if provider._rl_fallback():
                    logger.info("empty_instruments_first_attempt_retrying exch=%s", exch)
                raw_retry = call_with_retry(_fetch)
                if isinstance(raw_retry, list) and raw_retry:
                    raw = raw_retry
                    if provider._rl_fallback():
                        logger.info("empty_retry_success exch=%s count=%d", exch, len(raw))
            except Exception as _re:  # pragma: no cover
                if provider._rl_fallback():
                    logger.debug(f"empty_retry_failed exch={exch} err={_re}")
        if isinstance(raw, list):
            provider._state.instruments_cache[exch] = raw
            provider._state.instruments_cache_meta[exch] = now
            if not raw:
                provider._state.instruments_cache_meta[exch] = now - (ttl - 10) if ttl > 10 else now
                logger.debug("empty_instruments_cache_short_ttl exch=%s ttl=%s", exch, ttl)
            else:
                try:
                    sample_keys = list(raw[0].keys()) if raw else []
                    logger.debug("instrument_fetch_success exch=%s count=%d sample_keys=%s", exch, len(raw), sample_keys)
                except Exception:
                    pass
            return raw
        raise ValueError("unexpected_instruments_shape")
    except Exception as e:
        if _is_auth_error(e) or str(e) == 'kite_auth_failed':
            provider._auth_failed = True
            if provider._rl_fallback():
                logger.warning("Kite auth failed; using synthetic instruments. Set KITE_API_KEY/KITE_ACCESS_TOKEN for real API.")
        else:
            if provider._rl_fallback():
                logger.debug(f"Instrument fetch failed, using synthetic: {e}")
        try:
            handle_provider_error(e, component="kite_provider.get_instruments", context={"exchange": exch})
        except Exception:
            pass
    logger.warning("Kite instruments unavailable (auth or fetch failure); synthetic fallback disabled – returning empty list.")
    provider._state.instruments_cache[exch] = []
    provider._state.instruments_cache_meta[exch] = now - (ttl - 10) if ttl > 10 else now
    provider._used_fallback = True
    return []

__all__ = ["fetch_instruments"]
