"""Column Store Ingestion Pipeline (Phase 4A - Simulation Only)

Implements minimal ingestion buffer + batcher + metrics emission using the
pre-defined `column_store` metrics family. External writes are simulated so
we can validate metrics and backpressure behavior without a real backend yet.

Future phases will:
- Add real ClickHouse writer
- Implement retry with exponential backoff
- Support configurable serialization formats
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


class _SupportsMetricOps(Protocol):  # minimal structural typing for labels objects
    def set(self, value: float | int) -> Any: ...  # pragma: no cover - interface only
    def inc(self, value: float | int = 1) -> Any: ...
    def observe(self, value: float | int) -> Any: ...

def _safe(obj: Any) -> _SupportsMetricOps | None:
    return obj if obj is not None else None
import os
import threading
import time

try:
    from src.metrics import generated as m  # runtime-provided metrics family
except Exception:  # pragma: no cover - defensive fallback
    class _Dummy:
        def __getattr__(self, name: str):  # returns no-op callables preserving chain
            def _f(*_a: Any, **_k: Any):
                class _Leaf:
                    def set(self, *_a2: Any, **_k2: Any): pass
                    def inc(self, *_a2: Any, **_k2: Any): pass
                    def observe(self, *_a2: Any, **_k2: Any): pass
                return _Leaf()
            return _f
    m = _Dummy()
from src.metrics.safe_emit import safe_emit

# ---------------------------------------------------------------------------
# Configuration (environment driven – no centralized config system yet)
# ---------------------------------------------------------------------------

def _getenv_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, str(int(default)))
    return v.strip().lower() in {"1","true","yes","on"}

def _getenv_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

@dataclass
class PipelineConfig:
    enabled: bool = True
    table: str = "option_chain_agg"
    batch_rows: int = 4000
    max_latency_ms: int = 5000
    high_watermark_rows: int = 80000
    low_watermark_rows: int = 40000

    @staticmethod
    def from_env() -> PipelineConfig:
        return PipelineConfig(
            enabled=_getenv_bool("STORAGE_COLUMN_STORE_ENABLED", True),
            table=os.getenv("STORAGE_COLUMN_STORE_TABLE", "option_chain_agg"),
            batch_rows=_getenv_int("STORAGE_COLUMN_STORE_BATCH_ROWS", 4000),
            max_latency_ms=_getenv_int("STORAGE_COLUMN_STORE_MAX_LATENCY_MS", 5000),
            high_watermark_rows=_getenv_int("STORAGE_COLUMN_STORE_HIGH_WATERMARK_ROWS", 80000),
            low_watermark_rows=_getenv_int("STORAGE_COLUMN_STORE_LOW_WATERMARK_ROWS", 40000),
        )

# Row type for simulation: dict of column -> value
Row = dict[str, Any]

class _Buffer:
    def __init__(self):
        self.rows: list[Row] = []
        self.first_enqueue_ts: float | None = None

    def add(self, row: Row):
        if self.first_enqueue_ts is None:
            self.first_enqueue_ts = time.time()
        self.rows.append(row)

    def should_flush(self, batch_rows: int, max_latency_ms: int) -> bool:
        if not self.rows:
            return False
        if len(self.rows) >= batch_rows:
            return True
        if self.first_enqueue_ts is not None:
            age_ms = (time.time() - self.first_enqueue_ts) * 1000.0
            if age_ms >= max_latency_ms:
                return True
        return False

    def pop_all(self) -> list[Row]:
        out = self.rows
        self.rows = []
        self.first_enqueue_ts = None
        return out

class ColumnStorePipeline:
    def __init__(self, cfg: PipelineConfig):
        self.cfg = cfg
        self._buf = _Buffer()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Simulated failure injection hook
        self._fail_writer: Callable[[list[Row]], str | None] | None = None  # returns reason if failure
        if self.cfg.enabled:
            self._thread = threading.Thread(target=self._run, name="cs-ingest", daemon=True)
            self._thread.start()

    def install_failure_hook(self, fn: Callable[[list[Row]], str | None]):
        self._fail_writer = fn

    def enqueue(self, row: Row):
        if not self.cfg.enabled:
            return
        with self._lock:
            self._buf.add(row)
            self._update_backlog_metrics()

    def _update_backlog_metrics(self):
        try:
            backlog = len(self._buf.rows)
            _g = _safe(m.m_cs_ingest_backlog_rows_labels(self.cfg.table))
            if _g: _g.set(backlog)
            backpressure_active = 1 if backlog >= self.cfg.high_watermark_rows else 0
            _g2 = _safe(m.m_cs_ingest_backpressure_flag_labels(self.cfg.table))
            if _g2: _g2.set(backpressure_active)
        except Exception:
            pass

    def _run(self):  # pragma: no cover - timing loop
        while not self._stop.is_set():
            try:
                self._maybe_flush()
            except Exception:
                pass
            self._stop.wait(0.25)

    def _maybe_flush(self):
        with self._lock:
            if not self._buf.should_flush(self.cfg.batch_rows, self.cfg.max_latency_ms):
                return
            batch = self._buf.pop_all()
        if not batch:
            return
        start = time.perf_counter()
        failure_reason: str | None = None
        try:
            if self._fail_writer:
                reason = self._fail_writer(batch)
                if reason:
                    failure_reason = reason
            # Simulation: pretend write success if no failure reason set
        except Exception as e:  # pragma: no cover - defensive
            failure_reason = str(e.__class__.__name__)
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        @safe_emit(emitter="cs.ingest.batch")
        def _emit_batch_metrics():
            try:
                if failure_reason:
                    _c_fail = _safe(m.m_cs_ingest_failures_total_labels(self.cfg.table, failure_reason))
                    if _c_fail: _c_fail.inc()
                else:
                    rows = len(batch)
                    est_bytes = 0
                    try:
                        est_bytes = sum(sum(len(str(v)) for v in r.values()) for r in batch)
                    except Exception:
                        pass
                    _c_rows = _safe(m.m_cs_ingest_rows_total_labels(self.cfg.table))
                    if _c_rows: _c_rows.inc(rows)
                    _c_bytes = _safe(m.m_cs_ingest_bytes_total_labels(self.cfg.table))
                    if _c_bytes: _c_bytes.inc(est_bytes)
                    _h_lat = _safe(m.m_cs_ingest_latency_ms_labels(self.cfg.table))
                    if _h_lat: _h_lat.observe(elapsed_ms)
                # Update backlog (now empty after flush)
                backlog_now = len(self._buf.rows)
                _g_backlog = _safe(m.m_cs_ingest_backlog_rows_labels(self.cfg.table))
                if _g_backlog: _g_backlog.set(backlog_now)
                bp = 1 if backlog_now >= self.cfg.high_watermark_rows else 0
                _g_bp = _safe(m.m_cs_ingest_backpressure_flag_labels(self.cfg.table))
                if _g_bp: _g_bp.set(bp)
            except Exception:
                pass
        _emit_batch_metrics()

    def flush(self):
        self._maybe_flush()

    def shutdown(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        # Final flush
        try:
            self.flush()
        except Exception:
            pass

# Simple factory (singleton per table)
_PIPELINES: dict[str, ColumnStorePipeline] = {}

def get_pipeline(table: str = "option_chain_agg") -> ColumnStorePipeline:
    if table not in _PIPELINES:
        _PIPELINES[table] = ColumnStorePipeline(PipelineConfig.from_env())
    return _PIPELINES[table]

__all__ = ["PipelineConfig", "ColumnStorePipeline", "get_pipeline"]
