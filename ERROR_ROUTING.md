# Error Routing System

The error routing subsystem provides a centralized, data-driven mechanism to classify, log, and emit metrics for operational and data-quality events.

## Goals
- Eliminate scattered ad-hoc logging patterns.
- Standardize severity and metric emission.
- Support dynamic registration (feature flags / experiments) without code sprawl.
- Prevent log storms via throttling.
- Provide safe serialization of rich context objects.

## Core API
```python
from src.errors.error_routing import route_error, register_error, unregister_error

route_error('csv.schema.issues', logger, metrics, index='NIFTY', count=17)
```

### Signature
```python
route_error(code: str, logger, metrics=None, _count: int|float = 1, **labels) -> dict
```
Parameters:
- code: Registry key (e.g. `csv.junk.skip`).
- logger: Any logger supporting standard level methods.
- metrics: Metrics registry (optional). Metric name resolved from registry entry.
- _count: Amount to increment metric (default 1). Works for counters and gauges with `.inc()` semantics.
- **labels: Arbitrary context. Non-primitive values are JSON serialized (max ~512 chars) or replaced with `<unserializable>`.

Returns a dict with: `code`, `registered`, `log_level`, `severity`, `metric`, `throttled`.

## Registry Spec
Each entry in `ERROR_REGISTRY` supports:
| Field | Type | Description |
|-------|------|-------------|
| log_level | str | One of debug/info/warning/error/critical |
| metric | str? | Metric attribute name on metrics registry |
| suppress | bool? | (Reserved) Caller may suppress duplicate upstream logging |
| escalate_env | str? | Environment variable name; if truthy escalates one level |
| severity | str? | Overrides derived severity mapping |
| throttle_sec | float? | Minimum seconds between full log emissions for same code+level |
| serializer | callable? | Optional custom serializer(labels) -> dict |

Severity auto-mapping (if not provided):
- debug/info → low
- warning → medium
- error → high
- critical → critical

## Throttling Behavior
If `throttle_sec` is set, the first event logs at configured level; repeated events within the window are marked `throttled=1` and downgraded to debug (so visibility in verbose mode remains possible). Metric increments still occur each call unless your metric backend integrates internal rate limits.

## Dynamic Registration
```python
register_error('stream.bus.timeout', log_level='warning', metric='stream_timeouts_total', throttle_sec=5)
route_error('stream.bus.timeout', logger, metrics, partition='alpha', elapsed_ms=9123)
```
To remove:
```python
unregister_error('stream.bus.timeout')
```

## Integration Examples
### CSV Sink Mixed Expiry Prune
```python
route_error('csv.mixed_expiry.prune', logger, metrics, _count=dropped, index=index, expiry=expiry_code, dropped=dropped)
```
### Junk Skip
```python
route_error('csv.junk.skip', logger, metrics, index=index, expiry=expiry_code, offset=offset, category=decision.category)
```
### Schema Issues
```python
route_error('csv.schema.issues', logger, metrics, index=index, expiry=expiry_code, count=len(schema_issues))
```

## Safe Serialization
Complex context (lists/dicts) is JSON serialized with best-effort fallback. A `serialization_issue` label may be injected if a field fails.

## Recommended Usage Guidelines
1. Prefer one route per conceptual event (not per call site) to keep cardinality low.
2. Use `_count` when batching a total (e.g. dropped rows) rather than looping route calls.
3. Add `throttle_sec` for high-frequency noisy events (e.g. transient network retries).
4. Keep label set small and stable; avoid raw user input or high-cardinality IDs unless essential.
5. Escalate severity via env flags temporarily during incident investigations using `escalate_env` property.

## Testing Patterns
Use returned dict fields instead of parsing logs:
```python
r = route_error('csv.schema.issues', logger, metrics, index='NIFTY', count=3)
assert r['severity'] == 'medium'
assert r['registered']
```

## Future Extensions (Optional)
- Global fallback hook for unregistered codes → metrics.
- Structured sinks (e.g. JSON log writer) leveraging serialized labels.
- Rate-based suppression (N per minute) beyond time-window throttle.
- Aggregated periodic summaries per code.

---
Maintainers: Update `ERROR_REGISTRY` responsibly; treat it as part of the platform’s observability contract.
