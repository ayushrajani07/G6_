"""Phase 9: Async / Batched Quote Enrichment

Optional performance path for quote enrichment with:
  * Environment gated activation (default off)
  * Thread pool batching of provider.enrich_with_quotes calls
  * Graceful fallback to synchronous enrichment on any failure / empty result

Design Overview
---------------
Public API:
  enrich_quotes_async(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics, *,
                      batch_size=None, timeout_ms=None, return_meta=False, executor=None) -> Dict | (Dict, Meta)

Activation flag: G6_ENRICH_ASYNC=1|true|on
Config flags:
  G6_ENRICH_ASYNC_WORKERS (int, default=min(4, cpu_count()))
  G6_ENRICH_ASYNC_BATCH (int, optional) -> default None (single bulk call)
  G6_ENRICH_ASYNC_TIMEOUT_MS (int, default 3000)

Behavior:
  * If async disabled -> directly delegate to existing enrich_quotes
  * If batch_size is None -> still single provider call (parity guarantee) but records mode='async-single'
  * If batch_size > 0 -> split instruments into chunks; parallelize; merge maps
  * Any batch failure marks error; partial successes still merged
  * If final result empty & instruments non-empty -> retry sync once
  * Exceptions never propagate; always return dict (and meta if requested)

Meta structure (when return_meta=True):
  {
    'mode': 'async-batch' | 'async-single' | 'sync-fallback' | 'sync-direct',
    'batches': N,
    'failed_batches': F,
    'total_instruments': len(instruments),
    'enriched': len(result),
    'cache': False,  # reserved for future
    'retry_sync': bool,
    'batch_size': effective_batch_size,
    'timeout_ms': timeout_ms,
    'duration_ms': elapsed,
  }

Non-goals (Phase 9 scope):
  * True asyncio integration (future: could wrap in loop executor)
  * Intelligent adaptive batching
  * Advanced retry strategies per batch

"""
from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Any


# Deliberately avoid binding sync enrichment at import time so tests that monkeypatch
# src.collectors.modules.enrichment.enrich_quotes are reflected. We resolve lazily.
def _sync_enrich_func() -> Callable[[str, str, Any, list[dict[str, Any]], Any, Any], dict[str, Any]] | None:  # pragma: no cover - trivial indirection
    try:
        from src.collectors.modules.enrichment import enrich_quotes
        return enrich_quotes
    except Exception:
        return None

__all__ = [
    'enrich_quotes_async',
    'get_enrichment_mode',
    'EnrichmentExecutor',
]


def _env_flag(name: str) -> bool:
    return os.environ.get(name, '0').lower() in ('1','true','on','yes')


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


class EnrichmentExecutor:
    """Thin wrapper around ThreadPoolExecutor with lazy singleton pattern."""
    _lock = threading.Lock()
    _shared: EnrichmentExecutor | None = None

    def __init__(self, max_workers: int):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='enrich')
        self.max_workers = max_workers

    @classmethod
    def get_shared(cls) -> EnrichmentExecutor:
        if cls._shared is None:
            with cls._lock:
                if cls._shared is None:
                    workers = _env_int('G6_ENRICH_ASYNC_WORKERS', 4)
                    cls._shared = EnrichmentExecutor(max_workers=max(1, workers))
        return cls._shared

    def submit(self, fn: Callable[..., Any], *a: Any, **k: Any) -> Future:
        return self._executor.submit(fn, *a, **k)

    def shutdown(self, wait: bool = False) -> None:  # optional external cleanup
        self._executor.shutdown(wait=wait)


def _chunk(seq: list[Any], size: int) -> Iterable[list[Any]]:
    if size <= 0:
        yield seq
        return
    for i in range(0, len(seq), size):
        yield seq[i:i+size]


def _call_provider(providers: Any, instruments: list[dict[str, Any]]) -> Any:
    return providers.enrich_with_quotes(instruments)  # may raise


def _async_enabled() -> bool:
    # Re-evaluate each call so tests toggling env mid-process see updated state
    return _env_flag('G6_ENRICH_ASYNC')


def get_enrichment_mode() -> str:
    return 'async-enabled' if _async_enabled() else 'sync-only'


def enrich_quotes_async(
    index_symbol: str,
    expiry_rule: str,
    expiry_date: Any,
    instruments: list[dict[str, Any]],
    providers: Any,
    metrics: Any,
    *,
    batch_size: int | None = None,
    timeout_ms: int | None = None,
    return_meta: bool = False,
    executor: EnrichmentExecutor | None = None,
) -> Any:
    """Async/batched enrichment with safe fallback.

    Returns enriched dict (and meta if return_meta=True).
    """
    started = time.perf_counter()
    timeout_ms = timeout_ms or _env_int('G6_ENRICH_ASYNC_TIMEOUT_MS', 3000)
    effective_batch = batch_size if batch_size is not None else os.environ.get('G6_ENRICH_ASYNC_BATCH')
    try:
        if isinstance(effective_batch, str):
            effective_batch = int(effective_batch)
    except Exception:
        effective_batch = None

    if not _async_enabled() or not instruments:
        # Direct sync path (delegate identical to legacy enrichment)
        _sync = _sync_enrich_func()
        result: dict[str, Any] = _sync(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics) if _sync else {}
        if return_meta:
            meta = {
                'mode': 'sync-direct',
                'batches': 1,
                'failed_batches': 0,
                'total_instruments': len(instruments),
                'enriched': len(result),
                'cache': False,
                'retry_sync': False,
                'batch_size': None,
                'timeout_ms': timeout_ms,
                'duration_ms': (time.perf_counter()-started)*1000.0,
            }
            return result, meta
        return result

    # Async path
    mode = 'async-single'
    has_error = False
    futures: list[Future] = []
    merged: dict[str, Any] = {}

    # Single bulk call if no batching requested
    if not effective_batch:
        # Perform a single bulk provider call (no threading) but still classify as async-single
        try:
            merged = providers.enrich_with_quotes(instruments)
        except Exception:
            has_error = True
            merged = {}
            # fallback sync attempt if provider path failed
            _sync = _sync_enrich_func()
            if _sync:
                try:
                    merged = _sync(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics)
                    mode = 'sync-fallback'
                except Exception:
                    pass
    else:
        mode = 'async-batch'
        exec_inst = executor or EnrichmentExecutor.get_shared()
        for chunk in _chunk(instruments, int(effective_batch)):
            futures.append(exec_inst.submit(_call_provider, providers, chunk))
        # Collect with per-future timeout; share total budget proportionally
        per_future_timeout = (timeout_ms / 1000.0) if timeout_ms else None
        for fut in as_completed(futures, timeout=(timeout_ms/1000.0) if timeout_ms else None):
            try:
                part: dict[str, Any] = fut.result(timeout=per_future_timeout)
                if part:
                    for sym, row in part.items():
                        if sym not in merged:
                            merged[sym] = row
            except Exception:
                has_error = True
                continue

    retry_sync = False
    if (not merged) and instruments:
        # Fallback sync attempt if async yielded nothing (or error)
        retry_sync = True
        try:
            _sync = _sync_enrich_func()
            if _sync:
                merged = _sync(index_symbol, expiry_rule, expiry_date, instruments, providers, metrics)
                mode = 'sync-fallback'
        except Exception:
            merged = {}

    if return_meta:
        meta = {
            'mode': mode,
            'batches': 1 if mode == 'async-single' else (len(futures) or 1),
            'failed_batches': sum(1 for f in futures if f.done() and f.exception() is not None) if futures else (1 if has_error else 0),
            'total_instruments': len(instruments),
            'enriched': len(merged),
            'cache': False,
            'retry_sync': retry_sync,
            'batch_size': int(effective_batch) if effective_batch else None,
            'timeout_ms': timeout_ms,
            'duration_ms': (time.perf_counter()-started)*1000.0,
        }
        return merged, meta
    return merged
