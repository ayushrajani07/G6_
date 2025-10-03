# File Access Best Practices

This codebase should avoid direct JSON file reads for runtime status and panels. Use the unified components below to reduce I/O, ensure consistent snapshots, and simplify testing.

## Use StatusReader for runtime_status.json

- Caches recent reads and centralizes env/path handling.
- Wraps UnifiedDataSource under the hood.

Example:

```python
from src.utils.status_reader import get_status_reader

reader = get_status_reader()  # or get_status_reader("data/runtime_status.json")
st = reader.get_raw_status()
cycle = reader.get_cycle_data()
indices = reader.get_indices_data()
```

## Use UnifiedDataSource for panels/*.json

- Provides get_panel_data(name) and get_panel_raw(name)
- Includes small TTL cache and lightweight file-change detection (mtime-based)

```python
from src.data_access.unified_source import UnifiedDataSource, DataSourceConfig

uds = UnifiedDataSource()
uds.reconfigure(DataSourceConfig(panels_dir="data/panels"))
indices = uds.get_panel_data("indices")
raw_stream = uds.get_panel_raw("indices_stream")
```

## Avoid direct open()/json.load()

- If you must read a file directly (temporary code), ensure atomic writes on producers and tolerant reads on consumers.
- Prefer using the centralized helpers above. They already handle missing files and parse errors gracefully.

## Event-driven updates (optional)

When `src/utils/file_watch_events.py` is present, the unified source can publish best-effort change notifications on file mtime changes:

- STATUS_FILE_CHANGED when `runtime_status.json` changes
- PANEL_FILE_CHANGED when a panel JSON changes

The Summary UI subscribes to these events and forces a refresh immediately, while still honoring the regular meta/resource refresh cadence. This reduces perceived latency without tight polling. If the event bus isn’t available, the UI gracefully falls back to time-based refresh.

Notes:
- The event bus is process-local and thread-safe; subscribers should keep callbacks fast.
- Producers should maintain atomic writes (tmp + replace) to avoid partial reads.
