"""Micro-batching helper for Kite quote requests (Phase 2).

Goal: Collapse bursts of near-simultaneous `get_quote` calls into a single
underlying `kite.quote()` network request while preserving per‑caller response
shape and existing rate limiter / retry semantics.

Activation:
  Set `G6_KITE_QUOTE_BATCH=1` (or truthy variants) to enable.
  Optional window override (milliseconds): `G6_KITE_QUOTE_BATCH_WINDOW_MS` (default 15 ms).

Design:
  * Thread-safe singleton `QuoteBatcher` aggregated under module-level accessor.
  * Each caller contributes a list of fully formatted symbols (EXCH:SYMBOL).
  * First caller in an empty batch starts a short-lived aggregator thread which:
        - Sleeps for the configured batch window.
        - Atomically captures the accumulated symbol set.
        - Performs one provider network fetch with retry + (optional) rate limiter.
        - Distributes per-request filtered dicts (subset view) back to waiters.
  * Errors propagate uniformly to all pending requestors for that batch; callers
    fall back to existing upstream synthetic / retry logic in `quotes.get_quote`.

Non-goals (future extensions possible):
  * Cross-batch caching (handled by quotes module cache already).
  * Partial per-symbol error partitioning (all-or-nothing for simplicity).
  * Metrics (can be added after stability: batch_size, merged_calls_saved, wait_ms).

Concurrency & Safety:
  * Lock guards pending request list & symbol set.
  * Minimal window keeps added latency negligible while capturing bursts.
  * If batch thread fails catastrophically, exception distributed; caller path
    proceeds to fallback logic in `quotes.get_quote` (which will synthesize).

Limitations:
  * Uses wall clock sleep; very high contention with very small windows (<2ms)
    may under-utilize batching due to scheduler granularity.
  * Does not currently short-circuit if only a single requester arrives; still
    waits window_ms (low default). Can be optimized if needed (e.g., early fire).

"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Any

try:  # optional – present in Phase 1
    from .rate_limit import build_default_rate_limiter
except Exception:  # pragma: no cover
    build_default_rate_limiter = None  # type: ignore

from src.utils.retry import call_with_retry

_TRUTHY = {"1","true","yes","on"}

def batching_enabled() -> bool:
    try:
        return str(os.getenv("G6_KITE_QUOTE_BATCH","0")).lower() in _TRUTHY
    except Exception:
        return False

def _batch_window_ms() -> int:
    try:
        return int(os.getenv("G6_KITE_QUOTE_BATCH_WINDOW_MS","15") or 15)
    except Exception:
        return 15

@dataclass
class _Request:
    symbols: list[str]
    event: threading.Event
    # Ack event to allow distributor to release requests sequentially ensuring deterministic append order in tests
    ack: threading.Event
    result: dict[str, Any] | None = None
    error: BaseException | None = None


class QuoteBatcher:
    def __init__(self):
        self._lock = threading.Lock()
        self._pending: list[_Request] = []
        self._symbols: set[str] = set()
        self._batch_active = False

    def fetch(self, provider: Any, symbols: list[str]) -> dict[str, Any]:
        """Join (or start) a batch for the given formatted symbols.

        Returns dict subset containing only the requested symbols.
        May raise on network / rate limit errors (propagated from underlying call).
        """
        req = _Request(symbols=list(symbols), event=threading.Event(), ack=threading.Event())
        with self._lock:
            self._pending.append(req)
            self._symbols.update(symbols)
            start_batch = not self._batch_active
            if start_batch:
                self._batch_active = True
                window_ms = max(0, _batch_window_ms())
                t = threading.Thread(target=self._flush_after_window, args=(provider, window_ms/1000.0), daemon=True)
                t.start()
        # Wait for batch completion
        req.event.wait()
        if req.error:
            raise req.error  # propagate
        # Acknowledge reception so distributor can release next in sequence
        try:
            req.ack.set()
        except Exception:
            pass
        return req.result or {}

    def _flush_after_window(self, provider: Any, delay_s: float) -> None:
        try:
            time.sleep(delay_s)
            # Snapshot pending
            with self._lock:
                pending = list(self._pending)
                symbols = list(self._symbols)
                # Reset for next batch
                self._pending = []
                self._symbols = set()
                self._batch_active = False
            if not pending or not symbols:
                for r in pending:
                    r.result = {}
                    r.event.set()
                return
            raw = self._perform_fetch(provider, symbols)
            # Distribute filtered subsets
            # Release events sequentially waiting for ack to enforce stable ordering of caller append operations
            for r in pending:
                try:
                    subset = {s: raw[s] for s in r.symbols if isinstance(raw, dict) and s in raw}
                    r.result = subset
                except Exception as sub_err:
                    r.error = sub_err
                finally:
                    r.event.set()
                    try:
                        # Wait briefly for caller to acknowledge retrieval; timeout keeps progress if caller slow
                        r.ack.wait(0.05)
                    except Exception:
                        pass
        except BaseException as e:  # propagate error to all waiters
            with self._lock:
                pending = list(self._pending)
                self._pending = []
                self._symbols = set()
                self._batch_active = False
            for r in pending:
                r.error = e
                r.event.set()

    def _perform_fetch(self, provider: Any, symbols: list[str]) -> dict[str, Any]:
        kite = getattr(provider, 'kite', None)
        if kite is None:
            raise RuntimeError('kite_client_missing')
        # Optional limiter reuse
        limiter = None
        if build_default_rate_limiter and (str(os.getenv('G6_KITE_LIMITER','0')).lower() in _TRUTHY):
            limiter = getattr(provider, '_g6_quote_rate_limiter', None)
            if limiter is None:
                try:
                    limiter = build_default_rate_limiter()
                    provider._g6_quote_rate_limiter = limiter
                except Exception:
                    limiter = None
        timeout = getattr(getattr(provider, '_settings', None), 'kite_timeout_sec', 5.0)

        def _network_call():
            if limiter is not None:
                limiter.acquire()
            return kite.quote(symbols)

        try:
            raw = call_with_retry(lambda: _network_call())
            if limiter is not None:
                try:
                    limiter.record_success()
                except Exception:
                    pass
            return raw  # type: ignore[return-value]
        except Exception as e:
            if limiter is not None:
                msg = str(e).lower()
                if any(k in msg for k in ("too many requests","rate limit","429")):
                    try:
                        limiter.record_rate_limit_error()
                    except Exception:
                        pass
            raise

_BATCHER_SINGLETON: QuoteBatcher | None = None
_BATCHER_LOCK = threading.Lock()

def get_batcher() -> QuoteBatcher:
    global _BATCHER_SINGLETON
    if _BATCHER_SINGLETON is None:
        with _BATCHER_LOCK:
            if _BATCHER_SINGLETON is None:
                _BATCHER_SINGLETON = QuoteBatcher()
    return _BATCHER_SINGLETON

__all__ = ["batching_enabled", "get_batcher"]
