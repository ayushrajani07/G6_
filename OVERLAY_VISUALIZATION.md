# Weekday Overlay Visualization Guide

## Overview
This document describes how to generate and view weekday overlay plots combining live intraday option total premium (tp) and average total premium (avg_tp) with historical weekday arithmetic means and EMAs.

## Data Inputs
- Live CSV root: `data/g6_data/<INDEX>/<expiry_tag>/<offset>/<YYYY-MM-DD>.csv`
- Weekday master: `data/weekday_master/<Weekday>/<INDEX>_<expiry_tag>_<offset>.csv`

Each weekday master row contains: `timestamp,tp_mean,tp_ema,counter_tp,avg_tp_mean,avg_tp_ema,counter_avg_tp,index,expiry_tag,offset`.

## Plot Script
`python scripts/plot_weekday_overlays.py` renders HTML.

Internals note for contributors: common CSV loading, memory guards, and trace-building helpers are centralized in `src/utils/overlay_plotting.py`. Prefer using those helpers from new scripts to avoid duplication.

### Key Features
- 6 lines per key: tp (live/mean/ema) in blue; avg_tp (live/mean/ema) in orange.
- Layout modes: `by-index` (default), `grid` (multi-panel), `tabs` (one panel visible at a time), and `split` (two-column grid with synchronized zoom).
- JSON config to drive indices, expiry tags, offsets, layout, filters, and annotation behavior.
- EMA alpha annotation embedded in visible figure plus layout meta.
- Filter UI (grid layout) with dynamic panel hide/show.

### CLI Arguments
| Argument | Description |
|----------|-------------|
| `--live-root` | Root directory of live per-offset CSV data |
| `--weekday-root` | Root of weekday master overlays |
| `--date` | Trade date (YYYY-MM-DD) default today |
| `--index` | Repeatable index symbol filter |
| `--expiry-tag` | Repeatable expiry tag filter |
| `--offset` | Repeatable offset filter |
| `--output` | Output HTML filename |
| `--deviation` | Include deviation line (tp_live - tp_mean) |
| `--config-json` | Path to JSON configuration file |
| `--layout` | One of `by-index`, `grid`, `tabs`, `split` |
### Layout Details
- Tabs: Each (index, expiry, offset) renders into a tab; click headers to switch. Lightweight, good for many panels.
- Grid: Multiple panels arranged in a grid with filter checkboxes for expiry tags and offsets.
- Split: Two-column grid; x-axis zoom/pan is synchronized across panels for side-by-side comparison.

| `--alpha` | EMA alpha (annotation only) |
| `--min-count` | Minimum overlay sample count (counter_tp) to include |
| `--min-confidence` | Minimum relative confidence (counter_tp / max counter) in [0,1] |

### JSON Config Structure Example
```json
{
  "date": "2025-09-14",
  "indices": ["NIFTY", "BANKNIFTY"],
  "expiry_tags": ["this_week", "next_week"],
  "offsets": ["ATM", "OTM_1"],
  "layout": "grid",
  "max_columns": 3,
  "show_deviation": true,
  "alpha_annotation": true,
  "alpha": 0.35,
  "panel": {"height_per_panel": 300}
  "min_count": 10,
  "min_confidence": 0.5
}
```

### EMA Alpha Annotation
Displayed at top-left and stored in `layout.meta.ema`:
```json
{
  "ema": {
    "alpha": 0.35,
    "effective_window_buckets": 4.71,
    "generated_utc": "2025-09-14T04:10:22Z"
  }
}
```
Effective window approximates `(2/alpha) - 1` buckets (bucket = 30s).

### Grid Layout Filters
The grid layout generates a control panel with checkboxes for expiry tags and offsets. De-selecting a value hides all panels with that attribute pair.

## Sample Generation
Use `scripts/generate_overlay_layout_samples.py` to create synthetic demonstration HTML outputs:
```
python scripts/generate_overlay_layout_samples.py
```
Outputs placed in repository root: `sample_by_index.html`, `sample_grid.html`.

## Grafana Fallback
A snippet is provided in `grafana/dashboards/weekday_overlay_panel_snippet.json` to compare live tp vs weekday overlay mean/ema (requires Influx ingestion of overlay series).

## EOD Process (Recommended)
1. Run weekday overlay aggregation EOD: `python scripts/weekday_overlay.py --config config/g6_config.json --all`.
2. Next session, render overlays using plot script.
3. Optionally publish overlays to Influx for Grafana.

### Quality Reports and Backups
- The EOD aggregator writes a per-day quality report under `<output_dir>/_quality/overlay_quality_YYYY-MM-DD.json` summarizing updates and any issues (missing files, read/parse errors). Multiple runs append to the `runs` array.
- Set `G6_OVERLAY_WRITE_BACKUP=1` to save a `*.bak` of the existing master before the atomic replace. Useful for auditing and recovery.

### Trading Calendar and Time Tolerance
- To skip overlay aggregation on non-trading days (weekends and configured holidays), set `G6_OVERLAY_SKIP_NON_TRADING=1` before running `weekday_overlay.py`.
- Provide holidays via `G6_CALENDAR_HOLIDAYS_JSON` (path to a JSON file containing a list of `YYYY-MM-DD` strings or an object with `{"holidays": [...]}`), otherwise the tool looks for `data/weekday_master/_calendar/holidays.json`.
- For plotting alignment when timestamps are slightly misaligned, set `G6_TIME_TOLERANCE_SECONDS` (e.g., `30`) to round time buckets down to the nearest N seconds in loaders. This affects visualization only; source CSVs remain unchanged.

## Memory Management (Overlays Plot)

Large CSVs can be loaded in chunks with basic memory monitoring. Controls are available via CLI or environment variables.

- CLI flags:
  - `--memory-limit` (MB): Warn and trigger GC when process memory crosses this threshold.
  - `--chunk-size`: Read large CSVs in chunks of this many rows.
- Environment variables:
  - `G6_OVERLAY_VIS_MEMORY_LIMIT_MB` (default 768)
  - `G6_OVERLAY_VIS_CHUNK_SIZE` (default 5000)

Example:
```
python scripts/plot_weekday_overlays.py --live-root data/g6_data --weekday-root data/weekday_master ^
  --index NIFTY --expiry-tag this_week --offset 0 --memory-limit 1024 --chunk-size 20000
```

## Plotly bundle (local or pinned CDN)

The plotting HTML no longer depends on the unpinned Plotly “latest” CDN. A small resolver chooses the script source in this order:

1) Env override: `G6_PLOTLY_JS_PATH` (file path or URL)
2) Local bundle: `src/assets/js/plotly.min.js` (if present)
3) Pinned CDN: `https://cdn.plot.ly/plotly-<version>.min.js` where `<version>` defaults to `2.26.0` and can be overridden via `G6_PLOTLY_VERSION`.

Notes:
- To run fully offline, place a copy of `plotly.min.js` at `src/assets/js/plotly.min.js` or point `G6_PLOTLY_JS_PATH` to a reachable location.
- The plot script explicitly injects the `<script src='...'>` tag and sets `include_plotlyjs=False` for deterministic bundles.

Windows PowerShell example to use a custom bundle:

```powershell
$env:G6_PLOTLY_JS_PATH = "C:/tools/plotly-2.26.0.min.js"; python scripts/plot_weekday_overlays.py --layout grid
```

### Shared Helpers
- `src/utils/overlay_plotting.py` exposes:
  - `load_live_series`, `load_overlay_series`, `build_merged`
  - `add_traces` for Plotly figures
  - `annotate_alpha`, `effective_window`
  - `env_int`, `proc_mem_mb`, `monitor_memory`
  - `export_figure_image` (PNG via kaleido)
Use these utilities to keep plotting logic consistent across scripts.

## Future Enhancements
- Implement `tabs` and `split` layout rendering logic (currently grid + by-index implemented).
- Add z-score and volatility bands (needs variance tracking).
- Add PNG export automation via `kaleido`.
- Add dark theme switch.

## Troubleshooting
| Issue | Resolution |
|-------|------------|
| Missing overlay lines | Ensure weekday master file exists for the weekday. |
| Empty panel | No live CSV file for the selected key/date. |
| No EMA annotation | Set `alpha_annotation=true` or provide `--alpha`. |

## License & Notes
All generated HTML is client-side only; no external state mutation.
"""