# StatusReader and Unified Data Access

This note explains how to read runtime status and panels consistently using our unified layer.

## Why
- Eliminate duplicated JSON parsing and file IO scattered across scripts
- Centralize caching and environment overrides (paths, TTL, metrics URL)
- Make tests deterministic (DI + singleton with reset via reconfigure)

## Components
- `src/data_access/unified_source.py`: `UnifiedDataSource` and `DataSourceConfig`
  - Sources: metrics server (JSON), panels directory, runtime_status.json
  - Small TTL cache to avoid thrashing
  - Helpers: `get_runtime_status`, `get_indices_data`, `get_cycle_data`, `get_panel_data`, `get_panel_raw`, `get_metrics_data`, etc.
- `src/utils/status_reader.py`: thin wrapper tailored for runtime_status access with convenience getters
  - `get_raw_status()`, `get_cycle_data()`, `get_indices_data()`, `get_provider_data()`, `get_resources_data()`, `get_health_data()`
  - `get_typed(path, default)` for safe dotted-path extraction
  - `get_status_age_seconds()` heuristics using status timestamp or file mtime

## Usage

- Quick status access:
  ```py
  from src.utils.status_reader import get_status_reader
  reader = get_status_reader()  # or get_status_reader("data/runtime_status.json")
  st = reader.get_raw_status()
  cycle = reader.get_cycle_data()
  indices = reader.get_indices_data()
  ```

- Panels via unified data source (including metadata like updated_at/kind):
  ```py
  from src.data_access.unified_source import UnifiedDataSource, DataSourceConfig
  uds = UnifiedDataSource()
  uds.reconfigure(DataSourceConfig(panels_dir="data/panels"))
  indices_stream = uds.get_panel_raw("indices_stream")
  # or only the shape under `data` for other panels
  indices = uds.get_panel_data("indices")
  ```

- Metrics server JSON (if enabled):
  ```py
  metrics = uds.get_metrics_data()
  ```

## Environment knobs
- `G6_RUNTIME_STATUS`: path to runtime_status.json (default `data/runtime_status.json`)
- `G6_PANELS_DIR`: base directory for panel JSON (default `data/panels`)
- `G6_METRICS_URL`: Prometheus adapter JSON endpoint (default `http://127.0.0.1:9108/metrics`)
- `G6_DISABLE_METRICS_SOURCE`: `1/true` to skip live metrics
- Priority overrides:
  - `G6_SOURCE_PRIORITY_METRICS`, `G6_SOURCE_PRIORITY_PANELS`, `G6_SOURCE_PRIORITY_STATUS`, `G6_SOURCE_PRIORITY_LOGS`
  - `G6_FORCE_DATA_SOURCE` to force one source to the front (e.g., `panels`)

## FastAPI lifespan migration
- We replaced deprecated `@app.on_event("startup")` with FastAPI `lifespan` to start/stop the metrics cache in `src/web/dashboard/app.py`.
- Benefits: no deprecation warnings, clearer lifecycle, and clean shutdown.

## Testing notes
- TTL caching can mask quick successive reads; set a small TTL (e.g., 0.1) during tests via `DataSourceConfig(cache_ttl_seconds=0.1)` and `UnifiedDataSource().reconfigure(cfg)`.
- For singleton consumers (StatusReader, UnifiedDataSource), tests can reconfigure to point at temp dirs/files without restarting the process.
