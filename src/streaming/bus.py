from __future__ import annotations

"""Streaming bus abstraction layer.

Goals:
- Provide a minimal interface decoupling producers/consumers from concrete transport (in-memory, future Redis/NATS, etc.)
- Surface consistent metrics naming (g6_stream_*) aligned with existing in-memory bus metrics but transport-neutral.
- Support simple fan-out subscription with optional type filtering.
- Keep semantics at-most-once (same as current in-memory) initially; allow future extension for durability.

Design Notes:
- We intentionally do NOT bake persistence / acknowledgements yet; interface includes a placeholder ack for forward compat.
- Event schema hashing: we emit a gauge labelled by event type and schema_hash (stable hash of sorted payload keys) so that governance can detect drift.
- External backend selection is deferred to a factory using env var G6_STREAM_BACKEND (default: INMEM).
"""
import hashlib
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.bus.in_memory_bus import InMemoryBus  # reuse existing implementation for INMEM adapter
from src.metrics import generated as m  # type: ignore

StreamCallback = Callable[["StreamEvent"], None]

@dataclass(slots=True)
class StreamEvent:
    """Transport-neutral event representation.

    Fields intentionally mirror bus.event.Event for now; may diverge later for external transports.
    """
    id: int
    ts_unix_ms: int
    type: str
    key: str | None
    payload: dict[str, Any]
    meta: dict[str, Any] | None = None

@dataclass(slots=True)
class StreamPublishResult:
    event_id: int
    elapsed_ms: float

@runtime_checkable
class StreamSubscription(Protocol):
    def poll(self, batch_size: int = 100, timeout: float = 0.0) -> list[StreamEvent]: ...  # pragma: no cover
    def ack(self, last_id: int) -> None: ...  # pragma: no cover

@runtime_checkable
class AbstractStreamBus(Protocol):
    name: str
    def publish(self, event_type: str, payload: dict[str, Any], *, key: str | None = None, meta: dict[str, Any] | None = None) -> StreamPublishResult: ...  # pragma: no cover
    def subscribe(self, *, filter_fn: Callable[[str], bool] | None = None, from_id: int | None = None) -> StreamSubscription: ...  # pragma: no cover

_schema_hash_emitted: dict[str, str] = {}
_schema_lock = threading.Lock()

def _emit_schema_hash(bus_name: str, event_type: str, payload: dict[str, Any]):
    # Stable schema hash: sorted top-level keys; include nested key counts for a quick drift heuristic.
    keys: list[str] = []
    for k in sorted(payload.keys()):
        v = payload[k]
        if isinstance(v, dict):
            keys.append(f"{k}{{{len(v)}}}")
        else:
            keys.append(k)
    basis = ";".join(keys).encode()
    h = hashlib.sha1(basis).hexdigest()[:12]
    cache_key = f"{event_type}:{h}"
    with _schema_lock:
        if _schema_hash_emitted.get(event_type) == h:
            return
        _schema_hash_emitted[event_type] = h
    try:  # gauge with labels(type, schema_hash)=1
        m.m_stream_event_schema_hash_info_labels(bus_name, event_type, h).set(1)  # type: ignore[attr-defined]
    except Exception:
        pass

class _InMemoryStreamSubscription(StreamSubscription):
    def __init__(self, inner):
        self._inner = inner
    def poll(self, batch_size: int = 100, timeout: float = 0.0) -> list[StreamEvent]:
        events = self._inner.poll(batch_size=batch_size, timeout=timeout)
        out: list[StreamEvent] = []
        for e in events:
            out.append(StreamEvent(id=e.id, ts_unix_ms=e.ts_unix_ms, type=e.type, key=e.key, payload=e.payload, meta=e.meta))
        return out
    def ack(self, last_id: int) -> None:
        self._inner.ack(last_id)

class _InMemoryStreamBus(AbstractStreamBus):
    def __init__(self, name: str):
        self.name = name
        self._bus = InMemoryBus(name)
    def publish(self, event_type: str, payload: dict[str, Any], *, key: str | None = None, meta: dict[str, Any] | None = None) -> StreamPublishResult:
        start = time.perf_counter()
        event_id = self._bus.publish(event_type, payload, key=key, meta=meta)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        _emit_schema_hash(self.name, event_type, payload)
        try:
            m.m_stream_events_published_total_labels(self.name, event_type).inc()  # type: ignore[attr-defined]
            m.m_stream_publish_latency_ms_labels(self.name, event_type).observe(elapsed_ms)  # type: ignore[attr-defined]
        except Exception:
            pass
        return StreamPublishResult(event_id=event_id, elapsed_ms=elapsed_ms)
    def subscribe(self, *, filter_fn: Callable[[str], bool] | None = None, from_id: int | None = None) -> StreamSubscription:
        inner = self._bus.subscribe(filter_fn=filter_fn, from_id=from_id)
        return _InMemoryStreamSubscription(inner)

# Placeholder for future external adapter stub
class _StubExternalStreamBus(AbstractStreamBus):
    def __init__(self, name: str):
        self.name = name
    def publish(self, event_type: str, payload: dict[str, Any], *, key: str | None = None, meta: dict[str, Any] | None = None) -> StreamPublishResult:  # pragma: no cover - simple stub
        # In stub, we just record metrics and drop
        start = time.perf_counter()
        _emit_schema_hash(self.name, event_type, payload)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            m.m_stream_events_published_total_labels(self.name, event_type).inc()  # type: ignore[attr-defined]
            m.m_stream_publish_latency_ms_labels(self.name, event_type).observe(elapsed_ms)  # type: ignore[attr-defined]
            m.m_stream_events_dropped_total_labels(self.name, 'stub').inc()  # type: ignore[attr-defined]
        except Exception:
            pass
        return StreamPublishResult(event_id=-1, elapsed_ms=elapsed_ms)
    def subscribe(self, *, filter_fn: Callable[[str], bool] | None = None, from_id: int | None = None) -> StreamSubscription:  # pragma: no cover - stub
        raise NotImplementedError("Stub external backend does not support subscribe")

_backends: dict[str, AbstractStreamBus] = {}
_backend_lock = threading.Lock()

def get_stream_bus(name: str = 'core') -> AbstractStreamBus:
    backend = os.getenv('G6_STREAM_BACKEND', 'INMEM').upper()
    key = f"{backend}:{name}"
    with _backend_lock:
        if key in _backends:
            return _backends[key]
        if backend == 'INMEM':
            bus: AbstractStreamBus = _InMemoryStreamBus(name)
        elif backend in ('REDIS', 'NATS'):
            # For now, return stub until real implementation lands
            bus = _StubExternalStreamBus(name)
        else:
            raise ValueError(f"Unsupported G6_STREAM_BACKEND={backend}")
        _backends[key] = bus
        return bus

__all__ = [
    'AbstractStreamBus',
    'StreamEvent',
    'StreamPublishResult',
    'StreamSubscription',
    'get_stream_bus',
]
