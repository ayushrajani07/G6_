"""Instrument cache placeholder (Phase 4 A7).

Will progressively absorb logic from `KiteProvider.get_instruments` including:
- TTL handling
- Retry / backoff heuristics
- Synthetic fallback accounting

Current stub returns an empty list to avoid behavioural change risk.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from .logging_events import emit_event
from .metrics_adapter import metrics, time_observation

logger = logging.getLogger(__name__)

class InstrumentCache:
    def __init__(self) -> None:
        self._cache: dict[str, list[dict[str, Any]]] = {}
        self._meta: dict[str, float] = {}
        self._last_log_ts: float = 0.0

    def _allow_log(self, interval: float = 5.0) -> bool:
        now = time.time()
        if (now - self._last_log_ts) > interval:
            self._last_log_ts = now
            return True
        return False

    def get(self, exchange: str) -> list[dict[str, Any]]:
        # Later: reuse TTL semantics from legacy provider
        return self._cache.get(exchange, [])

    def set(self, exchange: str, instruments: list[dict[str, Any]]) -> None:
        self._cache[exchange] = instruments
        self._meta[exchange] = time.time()

    def load_all(self) -> list[dict[str, Any]]:  # compatibility placeholder
        out: list[dict[str, Any]] = []
        for v in self._cache.values():
            out.extend(v)
        return out

    # --- migrated logic (Phase 4 A15) ------------------------------------
    def get_or_fetch(
        self,
        exchange: str,
        fetch: Callable[[], list[dict[str, Any]] | Any],
        ttl: float = 600.0,
        force_refresh: bool = False,
        short_empty_ttl: float | None = None,
        retry_on_empty: bool = True,
        retry_fetch: Callable[[], list[dict[str, Any]] | Any] | None = None,
        now_func: Callable[[], float] = time.time,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Return cached instruments or fetch using provided callable.

        Returns (result, from_cache_flag).
        Implements TTL semantics similar to legacy provider:
          - If cached and fresh -> return immediately.
          - Empty lists get a shortened TTL to encourage retry.
          - Optional one-time retry if first fetch returns empty.
        """
        now = now_func()
        cached = self._cache.get(exchange)
        meta = self._meta.get(exchange, 0.0)
        if not force_refresh and cached is not None and (now - meta) < ttl:
            if cached:
                metrics().incr("provider_instruments_cache_total", outcome="hit", empty="0")
                emit_event(logger, "provider.instruments.cache", outcome="hit", exchange=exchange, empty=0)
                return cached, True
            # empty cached list: allow a brief window before retrying
            if (now - meta) < (short_empty_ttl or 5.0):
                metrics().incr("provider_instruments_cache_total", outcome="hit", empty="1")
                emit_event(logger, "provider.instruments.cache", outcome="hit", exchange=exchange, empty=1)
                return cached, True
            # else fall through to refresh
        elif force_refresh:
            logger.debug("instrument_cache.force_refresh exch=%s", exchange)

        # Perform fetch
        try:
            with time_observation("provider_instruments_fetch_seconds", exchange=exchange):
                raw = fetch()
        except Exception as e:  # pragma: no cover - fetch callable handles specifics
            if self._allow_log():
                logger.debug("instrument_fetch_failed exch=%s err=%s", exchange, e)
            self._cache[exchange] = []
            self._meta[exchange] = now - (ttl - 10) if ttl > 10 else now
            metrics().incr("provider_instruments_fetch_total", outcome="error")
            emit_event(logger, "provider.instruments.fetch", outcome="error", exchange=exchange)
            return [], False

        # Retry if empty and permitted
        if isinstance(raw, list) and not raw and retry_on_empty and retry_fetch:
            if self._allow_log():
                logger.info("instrument_fetch_empty_retrying exch=%s", exchange)
            try:
                with time_observation("provider_instruments_fetch_seconds", exchange=exchange, retry="1"):
                    raw_retry = retry_fetch()
                if isinstance(raw_retry, list) and raw_retry:
                    raw = raw_retry
                    if self._allow_log():
                        logger.info("instrument_fetch_empty_retry_success exch=%s count=%d", exchange, len(raw))
                        emit_event(logger, "provider.instruments.fetch", outcome="ok_retry", exchange=exchange, count=len(raw))
            except Exception as re:  # pragma: no cover
                if self._allow_log():
                    logger.debug("instrument_fetch_retry_failed exch=%s err=%s", exchange, re)

        if isinstance(raw, list):
            self._cache[exchange] = raw
            self._meta[exchange] = now
            if not raw:
                # shorten TTL so we retry soon
                self._meta[exchange] = now - (ttl - 10) if ttl > 10 else now
                logger.debug("instrument_cache.empty_short_ttl exch=%s ttl=%s", exchange, ttl)
                metrics().incr("provider_instruments_fetch_total", outcome="empty")
                emit_event(logger, "provider.instruments.fetch", outcome="empty", exchange=exchange)
            else:
                try:
                    sample_keys = list(raw[0].keys()) if raw else []
                    logger.debug("instrument_cache.fetch_success exch=%s count=%d sample_keys=%s", exchange, len(raw), sample_keys)
                except Exception:
                    pass
                metrics().incr("provider_instruments_fetch_total", outcome="ok")
                emit_event(logger, "provider.instruments.fetch", outcome="ok", exchange=exchange, count=len(raw))
            return raw, False
        else:  # unexpected shape
            if self._allow_log():
                logger.warning("instrument_fetch_unexpected_shape exch=%s type=%s", exchange, type(raw))
            self._cache[exchange] = []
            self._meta[exchange] = now - (ttl - 10) if ttl > 10 else now
            metrics().incr("provider_instruments_fetch_total", outcome="unexpected_shape")
            emit_event(logger, "provider.instruments.fetch", outcome="unexpected_shape", exchange=exchange)
            return [], False
