"""Core helper utilities for KiteProvider (A7 modularization step).

This module extracts non-essential orchestration logic from the monolithic
`kite_provider.py` to reduce its LOC and clarify responsibilities:

Functions:
    setup_rate_limiter(settings) -> (api_rl, last_log_ts, last_quote_log_ts)
        Attempts to use specialized helpers; falls back to simple RateLimiter.
    emit_startup_summary_if_needed(provider) -> None
        Delegates to startup_summary emitter and ensures a single fallback
        summary log if the delegated emission failed silently.

Both helpers are intentionally defensive: they catch and suppress exceptions to
preserve original provider resilience semantics.
"""
from __future__ import annotations

import logging
from typing import Any

from src.utils.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


def setup_rate_limiter(settings: Any) -> tuple[Any | None, float, float]:  # pragma: no cover - logic mirrored from provider
    try:
        from src.broker.kite.rate_limiter_helpers import (
            make_throttled_flags as _make_flags,
        )
        from src.broker.kite.rate_limiter_helpers import (
            setup_api_rate_limiter as _setup_rl,
        )
        api_rl = _setup_rl(settings)
        flags = _make_flags()
        return api_rl, flags['last_log_ts'], flags['last_quote_log_ts']
    except Exception:
        try:
            ms = getattr(settings, 'kite_throttle_ms', 0) or 0
        except Exception:
            ms = 0
        api_rl = RateLimiter(ms / 1000.0) if ms > 0 else None
        return api_rl, 0.0, 0.0


def emit_startup_summary_if_needed(provider: Any) -> None:  # pragma: no cover - behavior validated via existing tests
    try:
        from src.broker.kite.startup_summary import emit_startup_summary as _emit_summary
        _emit_summary(provider)
    except Exception:
        # Silently continue; fallback block below will attempt single inline emission
        pass
    # Fallback inline emission (mirrors logic originally embedded in provider)
    try:  # pragma: no cover (only triggered if delegated path missed emission)
        import src.broker.kite.startup_summary as _ss  # type: ignore
        if '_KITE_PROVIDER_SUMMARY_EMITTED' in _ss.__dict__:
            return  # already emitted successfully
        s = getattr(provider, '_settings', None)
        concise = int(bool(getattr(s, 'concise', True))) if s else 1
        throttle_ms = int(getattr(s, 'kite_throttle_ms', 0) or 0) if s else 0
        exp_fabrication = int(bool(getattr(s, 'allow_expiry_fabrication', True))) if s and hasattr(s, 'allow_expiry_fabrication') else 1
        cache_ttl = getattr(s, 'instruments_cache_ttl', None) if s else None
        retry_on_empty = int(bool(getattr(s, 'retry_on_empty', True))) if s and hasattr(s, 'retry_on_empty') else 1
        logger.info(
            "provider.kite.summary concise=%s throttle_ms=%s expiry_fabrication=%s cache_ttl=%s retry_on_empty=%s has_client=%s",
            concise, throttle_ms, exp_fabrication, cache_ttl, retry_on_empty, int(getattr(provider, 'kite', None) is not None)
        )
        try:
            _ss._KITE_PROVIDER_SUMMARY_EMITTED = True  # type: ignore[attr-defined]
        except Exception:
            pass
    except Exception:
        pass
