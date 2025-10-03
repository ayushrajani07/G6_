# Unified Model API

The unified model provides a stable, versioned representation of the summary
state that downstream plugins and tools can rely on without depending on the
raw runtime status shape or panel JSON layout.

## Rationale

Previously, snapshot assembly returned a purpose-built dataclass (`UnifiedSnapshot`)
with fields overlapping the eventual public contract. To enable evolution without
repeated downstream changes, a higher-level `UnifiedStatusSnapshot` model with a
clear schema version (`schema_version`) is introduced.

## API Entry Point

```python
from src.summary.unified.model import assemble_model_snapshot
model, diag = assemble_model_snapshot(runtime_status=status_dict,
                                      panels_dir="data/panels",
                                      include_panels=True,
                                      in_memory_panels=live_overrides)
```

Returns:
- `model`: `UnifiedStatusSnapshot` instance
- `diag`: diagnostics dict containing at least `warnings: List[str]`

## Key Fields

| Field | Type | Notes |
|-------|------|-------|
| `schema_version` | int | Increments only on breaking semantic changes |
| `ts_epoch` | float | Construction timestamp (seconds) |
| `cycle` | `CycleInfo` | Number, last duration, success rate, next run ETA |
| `market_status` | str | Normalized upper-case market state (e.g. OPEN / CLOSED) |
| `provider` | dict | Provider name, auth, latency (best-effort) |
| `resources` | dict | CPU / memory or system metrics (panel precedence) |
| `indices` | List[`IndexEntry`] | Consolidated indices with dq metrics |
| `dq` | `DQCounts` | Aggregated G/W/R counts + thresholds |
| `adaptive` | `AdaptiveSummary` | Alerts total, by type, severity counts, followups |
| `provenance` | dict | Source per logical section: status / panels / panels_mem |
| `meta` | dict | status_file, panels_dir, sources list |
| `raw_ref` | dict | Slim raw subset for debugging (not guaranteed stable) |

## Panel Precedence
Order of precedence when `include_panels=True`:
1. `in_memory_panels` (live SSE overrides)
2. Filesystem panels (JSON in `panels_dir`)
3. Baseline fields in `runtime_status`

## Diagnostics
`diag['warnings']` collects non-fatal parse or merge issues (e.g., `indices_merge_failed`).
A future version may include structured codes and counters.

## Adapter Removal
The transitional adapter (`from_legacy_unified_snapshot`) and legacy fallback path
have been removed. `assemble_model_snapshot` now always uses the native builder.
If a native build error occurs, a minimal empty snapshot is returned with
`diag = {'warnings': ['native_fail'], 'error': <msg>, 'native': False}`.
No further deprecation steps remain for the adapter.

## Versioning Policy
- Additive fields: same `schema_version`
- Renames / semantic changes: increment `SCHEMA_VERSION`
- Removal of fields: requires major increment + deprecation window

## Example
```python
status = {"market": {"status": "open"}, "indices_detail": {"NIFTY": {"dq": {"score_percent": 92}}}}
model, diag = assemble_model_snapshot(runtime_status=status, panels_dir=None, include_panels=False)
print(model.market_status, model.dq.green, diag['warnings'])
```

## Roadmap
- Adapter removal once fallback events go to zero
- Schema diff tool for validating downstream compatibility
- JSON schema export for external integrations

## See Also
- `UNIFIED_PLUGINS.md` for plugin contract and metrics
- `DEFERRED_ENHANCEMENTS.md` for planned improvements
