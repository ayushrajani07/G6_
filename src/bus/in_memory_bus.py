from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable

from src.metrics import generated as m
from src.metrics.safe_emit import safe_emit

from .event import Event


class Subscriber:
    def __init__(self, bus: InMemoryBus, name: str, filter_fn: Callable[[str], bool] | None, start_id: int | None):
        self._bus = bus
        self.name = name
        self._filter = filter_fn
        with bus._lock:
            self._next_id = start_id if start_id is not None else bus._next_id
            if self._next_id < bus._head_id:
                self._next_id = bus._head_id

    def poll(self, batch_size: int = 100, timeout: float = 0.0):
        deadline = time.time() + timeout if timeout > 0 else None
        out: list[Event] = []
        while True:
            with self._bus._lock:
                if self._next_id >= self._bus._next_id:
                    # nothing new
                    pass
                else:
                    # events index: id - head_id maps into deque index
                    for ev in self._bus._events:
                        if ev.id < self._next_id:
                            continue
                        if ev.id >= self._next_id + batch_size:
                            break
                        if self._filter and not self._filter(ev.type):
                            continue
                        out.append(ev)
                    if out:
                        self._next_id = out[-1].id + 1
                # update lag gauge
                try:
                    lag = (self._bus._next_id - self._next_id)
                    m.m_bus_subscriber_lag_events_labels(self._bus.name, self.name).set(lag)  # type: ignore[attr-defined]
                except Exception:
                    pass
            if out or not deadline:
                break
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            time.sleep(min(0.01, remaining))
        return out

    def ack(self, last_id: int):  # placeholder for future persistence semantics
        if last_id + 1 > self._next_id:
            self._next_id = last_id + 1

class InMemoryBus:
    def __init__(self, name: str, max_retained: int = 50000):
        self.name = name
        self.max_retained = max_retained
        self._lock = threading.RLock()
        self._events: deque[Event] = deque()
        self._next_id = 0
        self._head_id = 0
        self._sub_counter = 0

    def publish(self, event_type: str, payload: dict, key: str | None = None, meta: dict | None = None) -> int:
        start = time.perf_counter()
        with self._lock:
            ev_id = self._next_id
            self._next_id += 1
            ts_ms = int(time.time() * 1000)
            ev = Event(id=ev_id, ts_unix_ms=ts_ms, type=event_type, key=key, payload=payload, meta=meta)
            self._events.append(ev)
            if len(self._events) > self.max_retained:
                self._events.popleft()
                self._head_id += 1
                try:
                    m.m_bus_events_dropped_total_labels(self.name, 'overflow').inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
            @safe_emit(emitter="bus.publish.metrics")
            def _emit_core_metrics():
                m.m_bus_events_published_total_labels(self.name).inc()  # type: ignore[attr-defined]
                m.m_bus_queue_retained_events_labels(self.name).set(len(self._events))  # type: ignore[attr-defined]

            _emit_core_metrics()
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        try:
            # Histogram defined in ms, so record raw elapsed_ms value
            m.m_bus_publish_latency_ms_labels(self.name).observe(elapsed_ms)  # type: ignore[attr-defined]
        except Exception:
            pass
        return ev_id

    def subscribe(self, filter_fn: Callable[[str], bool] | None = None, from_id: int | None = None) -> Subscriber:
        with self._lock:
            sub_id = self._sub_counter
            self._sub_counter += 1
        name = f"s{sub_id}"
        return Subscriber(self, name, filter_fn, from_id)

    def head_id(self) -> int:
        with self._lock:
            return self._head_id

    def tail_id(self) -> int:
        with self._lock:
            return self._next_id - 1

# Simple factory / registry
_BUSES: dict[str, InMemoryBus] = {}

def get_bus(name: str = 'core') -> InMemoryBus:
    if name not in _BUSES:
        _BUSES[name] = InMemoryBus(name)
    return _BUSES[name]

__all__ = ["InMemoryBus", "Subscriber", "get_bus"]
