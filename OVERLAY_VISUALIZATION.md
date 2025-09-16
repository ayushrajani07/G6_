# Weekday Overlay Visualization Guide

## Overview
This document describes how to generate and view weekday overlay plots combining live intraday option total premium (tp) and average total premium (avg_tp) with historical weekday arithmetic means and EMAs.

## Data Inputs
- Live CSV root: `data/g6_data/<INDEX>/<expiry_tag>/<offset>/<YYYY-MM-DD>.csv`
- Weekday master: `data/weekday_master/<Weekday>/<INDEX>_<expiry_tag>_<offset>.csv`

Each weekday master row contains: `timestamp,tp_mean,tp_ema,counter_tp,avg_tp_mean,avg_tp_ema,counter_avg_tp,index,expiry_tag,offset`.

## Plot Script
`python scripts/plot_weekday_overlays.py` renders HTML.

### Key Features
- 6 lines per key: tp (live/mean/ema) in blue; avg_tp (live/mean/ema) in orange.
- Layout modes: `by-index` (default), `grid` (multi-panel), future `tabs` and `split` placeholders.
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
| `--alpha` | EMA alpha (annotation only) |

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
1. Run weekday overlay aggregation EOD: `python scripts/weekday_overlay.py --config config/g6_config.json --all --mode eod`.
2. Next session, render overlays using plot script.
3. Optionally publish overlays to Influx for Grafana.

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