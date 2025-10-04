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

from dataclasses import dataclass
from typing import List, Dict, Callable, Optional, Any
import threading
import time
import os

from src.metrics import generated as m  # type: ignore
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
    def from_env() -> "PipelineConfig":
        return PipelineConfig(
            enabled=_getenv_bool("STORAGE_COLUMN_STORE_ENABLED", True),
            table=os.getenv("STORAGE_COLUMN_STORE_TABLE", "option_chain_agg"),
            batch_rows=_getenv_int("STORAGE_COLUMN_STORE_BATCH_ROWS", 4000),
            max_latency_ms=_getenv_int("STORAGE_COLUMN_STORE_MAX_LATENCY_MS", 5000),
            high_watermark_rows=_getenv_int("STORAGE_COLUMN_STORE_HIGH_WATERMARK_ROWS", 80000),
            low_watermark_rows=_getenv_int("STORAGE_COLUMN_STORE_LOW_WATERMARK_ROWS", 40000),
        )

# Row type for simulation: dict of column -> value
Row = Dict[str, Any]

class _Buffer:
    def __init__(self):
        self.rows: List[Row] = []
        self.first_enqueue_ts: Optional[float] = None

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

    def pop_all(self) -> List[Row]:
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
        self._thread: Optional[threading.Thread] = None
        # Simulated failure injection hook
        self._fail_writer: Optional[Callable[[List[Row]], Optional[str]]] = None  # returns reason if failure
        if self.cfg.enabled:
            self._thread = threading.Thread(target=self._run, name="cs-ingest", daemon=True)
            self._thread.start()

    def install_failure_hook(self, fn: Callable[[List[Row]], Optional[str]]):
        self._fail_writer = fn

    def enqueue(self, row: Row):
        if not self.cfg.enabled:
            return
        with self._lock:
            self._buf.add(row)
            self._update_backlog_metrics()

    def _update_backlog_metrics(self):
        try:
            m.m_cs_ingest_backlog_rows_labels(self.cfg.table).set(len(self._buf.rows))  # type: ignore[attr-defined]
            backpressure_active = 1 if len(self._buf.rows) >= self.cfg.high_watermark_rows else 0
            m.m_cs_ingest_backpressure_flag_labels(self.cfg.table).set(backpressure_active)  # type: ignore[attr-defined]
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
        failure_reason: Optional[str] = None
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
            if failure_reason:
                m.m_cs_ingest_failures_total_labels(self.cfg.table, failure_reason).inc()  # type: ignore[attr-defined]
            else:
                rows = len(batch)
                # Approximate byte size (rough heuristic) for simulation
                est_bytes = sum(sum(len(str(v)) for v in r.values()) for r in batch)
                m.m_cs_ingest_rows_total_labels(self.cfg.table).inc(rows)  # type: ignore[attr-defined]
                m.m_cs_ingest_bytes_total_labels(self.cfg.table).inc(est_bytes)  # type: ignore[attr-defined]
                m.m_cs_ingest_latency_ms_labels(self.cfg.table).observe(elapsed_ms)  # type: ignore[attr-defined]
            # Update backlog (now empty after flush)
            m.m_cs_ingest_backlog_rows_labels(self.cfg.table).set(len(self._buf.rows))  # type: ignore[attr-defined]
            # Adjust backpressure flag (may clear)
            bp = 1 if len(self._buf.rows) >= self.cfg.high_watermark_rows else 0
            m.m_cs_ingest_backpressure_flag_labels(self.cfg.table).set(bp)  # type: ignore[attr-defined]
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
_PIPELINES: Dict[str, ColumnStorePipeline] = {}

def get_pipeline(table: str = "option_chain_agg") -> ColumnStorePipeline:
    if table not in _PIPELINES:
        _PIPELINES[table] = ColumnStorePipeline(PipelineConfig.from_env())
    return _PIPELINES[table]

__all__ = ["PipelineConfig", "ColumnStorePipeline", "get_pipeline"]
