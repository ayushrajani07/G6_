# Streaming Bus Prototype (Phase 3 Seed)

## Goal
Introduce minimal external/event streaming layer to decouple high-frequency option chain + panel diff events from in-process consumers and enable future historical capture & fan-out.

## Initial Scope (MVP)
| Component | Responsibility |
|-----------|----------------|
| Producer Adapter | Serializes normalized events (panel_diff, panel_full_summary, option_chain_snapshot) to bus topic/subject |
| Consumer Adapter | Subscribes to topics; applies basic filtering (index list, event types) |
| Schema Module | Provides pydantic/dataclass schemas + version hashing (e.g., `EVENT_SCHEMA_HASH`) |
| Metrics | Publish latency, consumer lag, serialization size, failures |

## Technology Candidates
| Backend | Pros | Cons | MVP Effort |
|---------|------|------|-----------|
| NATS | Lightweight, simple subjects, good fan-out | Requires separate server process | Low |
| Redis Streams | Ubiquitous, persistence, consumer groups | Backpressure handling & trimming complexity | Medium |
| Kafka | Durable, partition scaling | Operational overhead for small footprint | High |

Recommendation: Start with NATS (lowest friction) + abstract interface so Redis/Kafka can slot in later.

## Event Types (Initial)
```jsonc
// panel_diff
{
  "type": "panel_diff",
  "panel": "summary",
  "generation": 12345,
  "ts": 1733333333.123,
  "diff": {"indices": {"NIFTY": {...}}},
  "size_bytes": 2048
}
// panel_full_summary
{
  "type": "panel_full",
  "panel": "summary",
  "generation": 12346,
  "ts": 1733333340.050,
  "snapshot": {"indices": {"NIFTY": {...}}},
  "size_bytes": 55000
}
// option_chain_snapshot (aggregated slice)
{
  "type": "option_chain_snapshot",
  "index": "NIFTY",
  "mny_buckets": {"ATM": {...}},
  "dte_buckets": {"0-1d": {...}},
  "ts": 1733333340.500,
  "provider": "primary",
  "schema_version": 1
}
```

## Schema Governance
- Version each event type; embed `schema_version`.
- Compute combined JSON schema canonical hash; export gauge `g6_stream_event_schema_hash_info{hash=...}` similar to metrics spec.

## Minimal Interfaces
```python
class EventBusProducer(Protocol):
    def publish(self, subject: str, data: bytes) -> None: ...

class EventBusConsumer(Protocol):
    def subscribe(self, subject: str, handler: Callable[[bytes], None]) -> None: ...
```
Factory loads implementation via env `G6_STREAM_BUS_IMPL` (e.g., `nats`, `redis`, `inmemory`).

## Metrics (Proposed)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_stream_publish_total | counter | type | Events published per type |
| g6_stream_publish_latency_ms | histogram | type | Publish call latency |
| g6_stream_serialize_bytes | histogram | type | Serialized payload size |
| g6_stream_consumer_lag_seconds | gauge | type,consumer | Approx last event age - now |
| g6_stream_consumer_errors_total | counter | type,consumer | Handler exceptions |

## Backpressure & Flow Control
- For NATS: monitor pending bytes + implement size guard (drop or delay with metric `g6_stream_dropped_total{reason="overflow"}`).
- Option: adaptive slow mode—reduce diff frequency when backlog exceeds threshold.

## MVP Delivery Steps
1. Define schemas & hash metric.
2. Implement in-memory adapter (baseline, echo) for tests.
3. Implement NATS adapter (optional import errors handled gracefully if not installed).
4. Wire publisher in panel diff/full emission path (abstract behind flag `G6_STREAM_ENABLE=1`).
5. Add publish + serialize metrics.
6. Provide consumer example script printing events for debugging.

## Non-Goals (Initial)
- Exactly-once delivery
- Persistent replay store (will follow with column store integration phase)
- Complex routing/authorization

## Open Questions
- Do we require compression (e.g., zstd) before publish? (Add later behind env flag.)
- Should option chain snapshot events be diffed as well? (Future optimization.)

---
Prepared for inclusion in Phase 3 activation. Link from `grafna.md` once implementation starts.
