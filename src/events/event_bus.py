"""In-process event bus for panel push streaming.

Provides a lightweight publish/get_since interface with IST-normalized timestamps
suitable for SSE (Server-Sent Events) transport. Designed to run within the
orchestrator process; thread-safe for concurrent publishers.
"""
from __future__ import annotations

from collections import deque, Counter
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from threading import Lock
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple, Protocol, runtime_checkable, Union, Callable

try:  # Prefer system zoneinfo if available
    from zoneinfo import ZoneInfo
    IST: tzinfo = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover - fallback when zoneinfo missing
    IST = timezone(timedelta(hours=5, minutes=30))


@runtime_checkable
class _LabelsMixin(Protocol):
    def labels(self, **label_values: str) -> "_LabelsMixin": ...


@runtime_checkable
class CounterLike(_LabelsMixin, Protocol):
    def inc(self, amount: int | float = 1) -> None: ...


@runtime_checkable
class GaugeLike(_LabelsMixin, Protocol):
    def set(self, value: int | float) -> None: ...


@runtime_checkable
class HistogramLike(Protocol):
    def observe(self, value: int | float) -> None: ...


MetricType = Union[CounterLike, GaugeLike, HistogramLike]
RegisterFunc = Callable[..., Any]

# Legacy name retained for older helpers referencing _FALLBACK_IST
_FALLBACK_IST: tzinfo = IST


@dataclass(frozen=True)
class EventRecord:
    """Immutable representation of a published event."""

    event_id: int
    event_type: str
    timestamp_ist: str
    payload: Dict[str, Any]
    coalesce_key: Optional[str] = None

    def as_sse_payload(self) -> Dict[str, Any]:
        """Return dictionary ready for JSON serialization to SSE clients."""
        base = {
            "id": self.event_id,
            "sequence": self.event_id,
            "type": self.event_type,
            "timestamp_ist": self.timestamp_ist,
            "payload": self.payload,
        }
        # Pass through generation field if producer stored it inside payload root
        gen = None
        try:
            if isinstance(self.payload, dict):
                g = self.payload.get('_generation')
                if isinstance(g, int):
                    gen = g
        except Exception:
            pass
        if gen is not None:
            base['generation'] = gen
        return base


class EventBus:
    """Simple in-memory event bus with bounded history and coalescing."""

    # Class-level annotations for attributes populated in __init__ (aids static analysis)
    _coalesce_counts: Counter[str]
    _forced_full_last_reason_ts: Dict[str, float]
    _m_events_emitted: Optional[CounterLike]
    _m_events_coalesced: Optional[CounterLike]
    _m_backlog_capacity: Optional[GaugeLike]
    _m_last_id: Optional[GaugeLike]
    _m_forced_full_total: Optional[CounterLike]
    _m_conn_duration: Optional[HistogramLike]

    def __init__(self, max_events: int = 2048) -> None:
        if max_events <= 0:
            raise ValueError("max_events must be positive")
        self._lock = Lock()
        self._max_events = max_events
        self._events: Deque[EventRecord] = deque(maxlen=max_events)
        self._seq = 0
        # Map coalesce key -> event_id to allow targeted replacement
        self._coalesce_index: Dict[str, int] = {}
        # Per-type published counters (lifetime within process)
        self._type_counts: Counter[str] = Counter()
        # Backlog high-water mark (max len observed)
        self._highwater = 0
        # Active consumer count (incremented externally by SSE handler when integrated)
        self._consumers = 0
        # Lazy metrics registration placeholders (populated on first publish)
        self._metrics_registered = False
        self._m_events_total: Optional[CounterLike] = None
        self._m_backlog_current: Optional[GaugeLike] = None
        self._m_backlog_highwater: Optional[GaugeLike] = None
        self._m_consumers: Optional[GaugeLike] = None
        # Panel generation (increments only on panel_full) exposed via gauge
        self._generation = 0
        self._m_generation: Optional[GaugeLike] = None
        # Additional Phase 1 instrumentation placeholders
        self._m_events_emitted = None  # Counter (post-coalesce) labeled by type
        self._m_events_coalesced = None  # Counter labeled by type
        self._m_backlog_capacity = None  # Gauge static capacity
        self._m_last_id = None  # Gauge last emitted id
        self._m_forced_full_total = None  # Counter labeled by reason (future phase usage)
        # Phase 3: connection duration histogram placeholder
        self._m_conn_duration = None  # Histogram SSE connection duration seconds
        # Coalesced event counts (process lifetime)
        self._coalesce_counts = Counter()
        # Forced full guard bookkeeping (reason -> last forced unixtime) future phase
        self._forced_full_last_reason_ts = {}

    # ------------------------------------------------------------------
    # Internal metric helper utilities (DRY guarded interactions)
    # ------------------------------------------------------------------
    @staticmethod
    def _inc_metric(metric: Optional[CounterLike], amount: int | float = 1) -> None:
        if metric is None:
            return
        try:
            inc_fn = getattr(metric, 'inc', None)
            if callable(inc_fn):
                inc_fn(amount)
        except Exception:  # pragma: no cover
            pass

    @staticmethod
    def _inc_labeled_metric(metric: Optional[CounterLike], labels: Dict[str, str], amount: int | float = 1) -> None:
        if metric is None:
            return
        try:
            lbl_fn = getattr(metric, 'labels', None)
            if callable(lbl_fn):
                obj = lbl_fn(**labels)
                inc2 = getattr(obj, 'inc', None)
                if callable(inc2):
                    inc2(amount)
                return
            EventBus._inc_metric(metric, amount)
        except Exception:  # pragma: no cover
            pass

    @staticmethod
    def _set_gauge(gauge: Optional[GaugeLike], value: int | float) -> None:
        if gauge is None:
            return
        try:
            set_fn = getattr(gauge, 'set', None)
            if callable(set_fn):
                set_fn(value)
        except Exception:  # pragma: no cover
            pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _next_id(self) -> int:
        self._seq += 1
        return self._seq

    def _now_ist_iso(self) -> str:
        """Return current IST timestamp in ISO format (tz-aware)."""
        now = datetime.now(tz=IST)
        if now.tzinfo is None:  # defensive (should not happen)
            now = now.replace(tzinfo=IST)
        return now.astimezone(IST).isoformat()

    def _evict_coalesced(self, key: str) -> None:
        """Remove any existing event with matching coalesce key."""

        if key not in self._coalesce_index:
            return
        target_id = self._coalesce_index.pop(key)
        # Rebuild deque without the targeted event. Bounded size keeps cost low.
        filtered: Deque[EventRecord] = deque(maxlen=self._max_events)
        for event in self._events:
            if event.event_id != target_id:
                filtered.append(event)
        self._events = filtered

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def publish(
        self,
        event_type: str,
        payload: Dict[str, Any],
        *,
        coalesce_key: Optional[str] = None,
        timestamp_ist: Optional[str] = None,
    ) -> EventRecord:
        """Publish a new event and return the stored record.

        Parameters
        ----------
        event_type: str
            Logical type (e.g., 'panel_diff', 'panel_full', 'severity_update').
        payload: dict
            JSON-serializable payload.
        coalesce_key: optional str
            When provided, replaces the latest event with the same key instead of
            appending another entry (helps avoid backlogs for rapid-fire updates).
        timestamp_ist: optional str
            Override the timestamp; must already be IST ISO string. Primarily for
            tests. When omitted we emit the current IST time.
        """

        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        if not event_type:
            raise ValueError("event_type cannot be empty")
        with self._lock:
            if coalesce_key:
                self._evict_coalesced(coalesce_key)
            event_id = self._next_id()
            ts = timestamp_ist or self._now_ist_iso()
            record = EventRecord(
                event_id=event_id,
                event_type=event_type,
                timestamp_ist=ts,
                payload=payload,
                coalesce_key=coalesce_key,
            )
            self._events.append(record)
            if coalesce_key:
                self._coalesce_index[coalesce_key] = event_id
                # Increment coalesced metrics
                EventBus._inc_labeled_metric(self._m_events_coalesced, {'type': event_type})
                self._coalesce_counts[event_type] += 1
            # Update per-type counters & backlog stats
            self._type_counts[event_type] += 1
            cur_len = len(self._events)
            if cur_len > self._highwater:
                self._highwater = cur_len
            # Metrics (lazy registration to avoid import cost when unused)
            self._maybe_register_metrics()
            # New emitted counter & last id gauge
            EventBus._inc_labeled_metric(self._m_events_emitted, {'type': event_type})
            if self._m_last_id is not None:
                EventBus._set_gauge(self._m_last_id, self._seq)
            # Metrics updates (best-effort; tolerate missing methods)
            EventBus._inc_labeled_metric(self._m_events_total, {'type': event_type})
            m_backlog_cur = self._m_backlog_current
            EventBus._set_gauge(m_backlog_cur, cur_len)
            m_backlog_hw = self._m_backlog_highwater
            if m_backlog_hw is not None:
                try:
                    set_fn = getattr(m_backlog_hw, 'set', None)
                    if callable(set_fn):
                        set_fn(self._highwater)
                except Exception:
                    pass
            # Generation gauge update (panel_full => increment; panel_diff carries current)
            if event_type == 'panel_full':
                self._generation += 1
            if isinstance(record.payload, dict):  # embed generation in payload for downstream clients
                try:
                    record.payload['_generation'] = self._generation  # mutate after store acceptable (immutable contract external)
                    # Inject server publish unixtime for latency measurement if not already present
                    if event_type in ('panel_full','panel_diff') and 'publish_unixtime' not in record.payload:
                        import time as _t
                        record.payload['publish_unixtime'] = _t.time()
                except Exception:
                    pass
            EventBus._set_gauge(self._m_generation, self._generation)
            # Update last_full unixtime gauge if registered (lazy registration handled elsewhere)
            if event_type == 'panel_full':
                try:
                    if hasattr(self, '_m_last_full_unixtime') and self._m_last_full_unixtime is not None:
                        set_fn = getattr(self._m_last_full_unixtime, 'set', None)
                        if callable(set_fn):
                            import time as _t
                            set_fn(_t.time())
                    else:
                        # Last resort: ensure gauge exists so downstream tests scraping registry find it.
                        try:
                            from prometheus_client import Gauge as _Gauge
                            self._m_last_full_unixtime = _Gauge('g6_events_last_full_unixtime', 'Unix timestamp of last panel_full event published')  # type: ignore[attr-defined]
                            try:
                                self._m_last_full_unixtime.set(__import__('time').time())  # type: ignore[attr-defined]
                            except Exception:
                                pass
                        except Exception:
                            pass
                except Exception:
                    pass
            return record

    # ------------------------------------------------------------------
    # Phase 4: Snapshot guard main entrypoint
    # ------------------------------------------------------------------
    def enforce_snapshot_guard(self) -> Optional[EventRecord]:
        """Force emit a panel_full snapshot if guard conditions breached.

        Conditions (all configurable via env):
          1. Missing baseline: no panel_full ever published and at least one diff seen.
          2. Generation regression: latest diff payload has _generation lower than bus generation.
          3. Gap exceeded: (latest_id - last_full_id) > G6_EVENTS_SNAPSHOT_GAP_MAX (default 500).

        Returns EventRecord if a panel_full was forced, else None.
        """
        # Fast reject if no events yet
        with self._lock:
            if not self._events:
                return None
            # Identify latest panel_full id
            last_full_id = 0
            for ev in reversed(self._events):
                if ev.event_type == 'panel_full':
                    last_full_id = ev.event_id
                    break
            latest_id = self._seq
            try:
                gap_max = int(os.environ.get('G6_EVENTS_SNAPSHOT_GAP_MAX','500'))
            except Exception:
                gap_max = 500
            need_full_reason: Optional[str] = None
            if last_full_id == 0:
                # Have we emitted any diff? If so baseline missing.
                for ev in self._events:
                    if ev.event_type == 'panel_diff':
                        need_full_reason = 'missing_baseline'
                        break
            else:
                if latest_id - last_full_id > gap_max:
                    need_full_reason = 'gap_exceeded'
            # Generation mismatch check: latest diff generation lower than bus generation
            if need_full_reason is None:
                for ev in reversed(self._events):
                    if ev.event_type in ('panel_diff','panel_full') and isinstance(ev.payload, dict):
                        gen = ev.payload.get('_generation')
                        if isinstance(gen, int) and gen < self._generation:
                            need_full_reason = 'generation_mismatch'
                        break
            if need_full_reason is None:
                return None
        # Outside lock: produce snapshot (copy) and publish forced full (coalesce key panel_full)
        snap = self.latest_full_snapshot()
        if snap is None:
            # Build synthetic snapshot from latest diff status if possible
            with self._lock:
                for ev in reversed(self._events):
                    if ev.event_type == 'panel_diff' and isinstance(ev.payload, dict):
                        # diff payload does not contain full status; cannot reconstruct -> abort
                        snap = {}
                        break
        if not self._record_forced_full(need_full_reason):  # cooldown enforced
            return None
        try:
            if isinstance(snap, dict):
                snap['_forced_full_reason'] = need_full_reason
            return self.publish('panel_full', {'status': snap or {}, 'forced_reason': need_full_reason}, coalesce_key='panel_full')
        except Exception:
            return None

    def latest_id(self) -> int:
        with self._lock:
            return self._seq

    def get_since(self, last_event_id: int, limit: Optional[int] = None) -> List[EventRecord]:
        """Return events with id greater than *last_event_id* in arrival order."""

        with self._lock:
            items: Iterable[EventRecord] = (e for e in self._events if e.event_id > last_event_id)
            if limit is not None and limit >= 0:
                out: List[EventRecord] = []
                for e in items:
                    out.append(e)
                    if len(out) >= limit:
                        break
                return out
            return list(items)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
            self._coalesce_index.clear()
            self._highwater = 0
            m_backlog_cur = self._m_backlog_current
            EventBus._set_gauge(m_backlog_cur, 0)

    def latest_full_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the most recent panel_full payload (including embedded _generation) if present.

        Scans from the right (newest) side of the deque for first panel_full event.
        Returns a shallow copy so callers can safely mutate without affecting stored record.
        """
        with self._lock:
            for ev in reversed(self._events):
                if ev.event_type == 'panel_full' and isinstance(ev.payload, dict):
                    try:
                        return dict(ev.payload)
                    except Exception:
                        return ev.payload  # fallback best-effort
            return None

    # ------------------------------------------------------------------
    # Metrics & Stats Accessors
    # ------------------------------------------------------------------
    def _maybe_register_metrics(self) -> None:
        """Register metrics under 'events' group exactly once.

        Avoids importing metrics registry until first publish to keep startup lean when
        events subsystem unused.
        """
        if self._metrics_registered:
            return
        # Optimistically mark to prevent recursive re-entry in rare error paths
        self._metrics_registered = True
        # Default all metric attributes so later code can rely on existence (even if None)
        self._m_events_total = None
        self._m_backlog_current = None
        self._m_backlog_highwater = None
        self._m_consumers = None
        self._m_generation = None
        self._m_last_full_unixtime = None
        self._m_events_dropped = None
        self._m_events_full_recovery = None
        self._m_events_emitted = None
        self._m_events_coalesced = None
        self._m_backlog_capacity = None
        self._m_last_id = None
        self._m_forced_full_total = None
        self._m_conn_duration = None
        try:
            registry = None
            try:
                from src.metrics import metrics as _metrics_mod  # type: ignore
                get_metrics_fn = getattr(_metrics_mod, 'get_metrics', None)
                if callable(get_metrics_fn):
                    registry = get_metrics_fn()
            except Exception:
                registry = None
            _register = getattr(registry, '_register', None) if registry is not None else None
            if callable(_register):
                from prometheus_client import Counter as _Counter, Gauge as _Gauge, Histogram as _Histogram
                from typing import cast as _cast
                # Core counters / gauges (failure tolerant individually)
                from typing import Any as _Any
                def _safe(reg_cls, name: str, doc: str, **kw) -> _Any:  # local helper tolerant to duplicates
                    try:
                        return _register(reg_cls, name, doc, **kw)  # type: ignore[misc]
                    except Exception:
                        return None
                self._m_events_total = _cast(CounterLike, _safe(_Counter, 'g6_events_published_total', 'Events published (labeled by type)', labelnames=['type']))
                self._m_backlog_current = _cast(GaugeLike, _safe(_Gauge, 'g6_events_backlog_current', 'Current event backlog size'))
                self._m_backlog_highwater = _cast(GaugeLike, _safe(_Gauge, 'g6_events_backlog_highwater', 'High-water mark for event backlog size'))
                self._m_consumers = _cast(GaugeLike, _safe(_Gauge, 'g6_events_consumers', 'Active SSE consumers'))
                self._m_generation = _cast(GaugeLike, _safe(_Gauge, 'g6_events_generation', 'Current panel generation (increments on panel_full)'))
                self._m_last_full_unixtime = _cast(GaugeLike, _safe(_Gauge, 'g6_events_last_full_unixtime', 'Unix timestamp of last panel_full event published'))
                self._m_events_dropped = _cast(CounterLike, _safe(_Counter, 'g6_events_dropped_total', 'Events dropped (reason,type)', labelnames=['reason','type']))
                self._m_events_full_recovery = _cast(CounterLike, _safe(_Counter, 'g6_events_full_recovery_total', 'Client-forced full snapshot recoveries'))
                self._m_events_emitted = _cast(CounterLike, _safe(_Counter, 'g6_events_emitted_total', 'Events emitted to backlog (post-coalesce)', labelnames=['type']))
                self._m_events_coalesced = _cast(CounterLike, _safe(_Counter, 'g6_events_coalesced_total', 'Events coalesced (replaced prior with same key)', labelnames=['type']))
                self._m_backlog_capacity = _cast(GaugeLike, _safe(_Gauge, 'g6_events_backlog_capacity', 'Configured event backlog capacity (max events)'))
                if self._m_backlog_capacity is not None:
                    try:
                        self._m_backlog_capacity.set(self._max_events)
                    except Exception:
                        pass
                self._m_last_id = _cast(GaugeLike, _safe(_Gauge, 'g6_events_last_id', 'Last emitted event id'))
                self._m_forced_full_total = _cast(CounterLike, _safe(_Counter, 'g6_events_forced_full_total', 'Forced panel_full emissions by snapshot guard', labelnames=['reason']))
                self._m_conn_duration = _cast(HistogramLike, _safe(_Histogram, 'g6_events_sse_connection_duration_seconds', 'SSE connection duration in seconds'))
            # If helper path failed to create the last_full gauge, perform a direct best-effort registration.
            if self._m_last_full_unixtime is None:
                try:
                    from prometheus_client import Gauge as _Gauge
                    self._m_last_full_unixtime = _Gauge('g6_events_last_full_unixtime', 'Unix timestamp of last panel_full event published')
                except Exception:
                    self._m_last_full_unixtime = None
        except Exception:
            # Swallow: metrics are optional; event bus must remain functional.
            pass

    # ------------------------------------------------------------------
    # Phase 3: connection duration observation
    # ------------------------------------------------------------------
    def _observe_connection_duration(self, seconds: float) -> None:
        """Observe SSE connection lifetime in histogram (best-effort)."""
        if seconds < 0:
            return
        try:
            if self._m_conn_duration is None:
                # Metrics may not yet be registered if no publish occurred.
                self._maybe_register_metrics()
            hist = getattr(self, '_m_conn_duration', None)
            if hist is not None:
                observe = getattr(hist, 'observe', None)
                if callable(observe):
                    observe(seconds)
        except Exception:  # pragma: no cover - observability best-effort
            pass

    def stats_snapshot(self) -> Dict[str, Any]:
        """Return a thread-safe snapshot of bus stats for external endpoints."""
        with self._lock:
            if self._events:
                oldest = self._events[0].event_id
            else:
                oldest = 0
            return {
                'latest_id': self._seq,
                'oldest_id': oldest,
                'backlog': len(self._events),
                'highwater': self._highwater,
                'types': dict(self._type_counts),
                'coalesced': dict(self._coalesce_counts),
                'consumers': self._consumers,
                'max_events': self._max_events,
                'generation': self._generation,
                'forced_full_last': dict(self._forced_full_last_reason_ts),
            }

    # ------------------------------------------------------------------
    # Phase 4: forced full snapshot guard helpers
    # ------------------------------------------------------------------
    def _record_forced_full(self, reason: str) -> bool:
        """Record a forced full emission for guard reason; returns True if allowed (cooldown passed).

        Cooldown seconds: G6_EVENTS_FORCE_FULL_RETRY_SECONDS (default 30).
        Increments metric g6_events_forced_full_total{reason} when emitted.
        """
        now = None
        try:
            import time as _t
            now = _t.time()
        except Exception:
            return False
        try:
            cooldown = float(os.environ.get('G6_EVENTS_FORCE_FULL_RETRY_SECONDS','30'))
        except Exception:
            cooldown = 30.0
        with self._lock:
            last_ts = self._forced_full_last_reason_ts.get(reason, 0.0)
            if now - last_ts < cooldown:
                return False
            self._forced_full_last_reason_ts[reason] = now
            EventBus._inc_labeled_metric(self._m_forced_full_total, {'reason': reason})
            return True

    # Consumer bookkeeping hooks (invoked by SSE handler integration later)
    def _consumer_started(self) -> None:
        with self._lock:
            self._consumers += 1
            EventBus._set_gauge(self._m_consumers, self._consumers)

    def _consumer_stopped(self) -> None:
        with self._lock:
            if self._consumers > 0:
                self._consumers -= 1
            EventBus._set_gauge(self._m_consumers, self._consumers)


_GLOBAL_BUS: Optional[EventBus] = None


def get_event_bus(max_events: int = 2048) -> EventBus:
    """Return the global singleton event bus, creating it if necessary."""

    global _GLOBAL_BUS
    if _GLOBAL_BUS is None:
        _GLOBAL_BUS = EventBus(max_events=max_events)
    return _GLOBAL_BUS


__all__ = ["EventBus", "EventRecord", "get_event_bus"]
