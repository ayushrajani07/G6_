# Panels Factory

A single source of truth for building panel JSON payloads used by the TUI and dashboard. This avoids duplication across scripts and ensures consistent formats.

## Modules
- `src/panels/models.py` — TypedDicts describing panel shapes (provider, resources, loop, indices summary, indices stream item). Types are intentionally permissive for backward compatibility.
- `src/panels/factory.py` — Builders that derive panel payloads from runtime status via `StatusReader`.

## API
- `build_panels(reader: StatusReader, status: dict) -> dict[str, Any]`
  - Returns standard panels:
    - `provider` — name, version, mode
    - `resources` — cpu_pct, rss_mb, peak_rss_mb
    - `sinks` — passthrough from status when present
    - `health` — passthrough health object
    - `loop` — cycle, last_start, last_duration, success_rate
    - `indices` — summary of indices with dq buckets
- `build_indices_stream_items(reader: StatusReader, status: dict) -> list[dict]`
  - Returns per-index stream rows with fields like `index`, `cycle`, `time`, `legs`, `avg`, `success`, `dq`, and a computed `status` (OK/WARN/ERROR).

## Usage Examples

### Bridge (transactional panels publish)
```
from src.utils.status_reader import StatusReader
from src.panels.factory import build_panels, build_indices_stream_items
from src.output.router import OutputRouter

reader = StatusReader()
status = reader.get_status()
panels = build_panels(reader, status)
items = build_indices_stream_items(reader, status)

router = OutputRouter()
with router.begin_panels_txn() as txn:
    for name, payload in panels.items():
        txn.panel_update(name, payload)
    for item in items:
        txn.panel_append("indices_stream", item)
```

### Updater (transactional, recommended)
```
from src.utils.status_reader import StatusReader
from src.panels.factory import build_panels, build_indices_stream_items
from src.utils.output import get_output

reader = StatusReader()
status = reader.get_status()
router = get_output(reset=True)

with router.begin_panels_txn():
    for name, payload in build_panels(reader, status).items():
        router.panel_update(name, payload, kind=name)
    for item in build_indices_stream_items(reader, status):
        router.panel_append("indices_stream", item, cap=50, kind="stream")
```

### Updater (legacy per-file atomic writes, not recommended)
```
from src.utils.status_reader import StatusReader
from src.panels.factory import build_panels, build_indices_stream_items
from src.utils.path_utils import data_subdir
import json, os, tempfile

reader = StatusReader()
status = reader.get_status()
panels = build_panels(reader, status)

panels_dir = data_subdir("panels")
for name, payload in panels.items():
    path = os.path.join(panels_dir, f"{name}.json")
    # atomic write (legacy; use router transactions instead)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=os.path.dirname(path), encoding="utf-8") as tmp:
        json.dump(payload, tmp, indent=2)
        tmp_path = tmp.name
    os.replace(tmp_path, path)
```

## Notes
- The factory gracefully handles missing fields by deriving indices/cycle from status when needed.
- `indices_stream.json` is preferred as a simple list; code still tolerates legacy dict wrappers when merging.
- Keep transactional writes (bridge) or atomic writes (updater) to avoid partial reads by consumers.
- Legs derivation precedence in indices panels/stream:
    1) If an `expiries` breakdown exists, sum per-expiry `legs` to get the per-index per-cycle total.
    2) Else, use `current_cycle_legs` when present.
    3) Else, fall back to cumulative counters: `legs`, `legs_total`, `options`, `options_count`, or `count`.
    This ensures per-cycle totals are used when detailed data is available and avoids showing inflated cumulative values.
- Cadence alignment: stream items carry the collector cycle and are appended once per cycle by the bridge, preventing per-second duplicates and keeping UI counters aligned with the collector.

### Description column (Indices Stream)
- Priority of content shown in the Description column (handled in `scripts/summary/panels/indices.py`):
    1) dq_labels — recent, concise data‑quality labels (e.g., `next_week_price_outlier`, `iv_out_of_range`).
    2) Correlated collector errors for the index/cycle/time window.
    3) status_reason — fallback textual reason from the panels helpers when nothing else is available.
- The Description intentionally avoids repeating numeric metrics (success%, counts). It focuses on root‑cause hints.

### Windows‑safe atomic writes
- All panel writers use centralized helpers in `src/utils/output.py` to perform fsync + replace with retries on Windows.
- This prevents temp‑file races and partial reads by consumers like the TUI and web dashboard.
