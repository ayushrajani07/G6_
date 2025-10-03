# Weekday Overlays – Live Updates and Theming

This guide explains how the overlays HTML enables optional live updates on top of static weekday averages, and how to test it locally using the mock server.

## JSON contract (polled by the page)

```
{
  "panels": {
    "<divId>": {
      "x": ["2025-09-24T10:00:00Z", ...],
      "y": [123.4, ...],
      "layout": { "annotations": [], "shapes": [] }
    },
    ...
  }
}
```

- divId: The Plotly div id. In grid/tabs/split modes we assign ids like `panel-<INDEX>-<EXPIRY>-<OFFSET>`.
- x: ISO-8601 timestamps with Z (UTC).
- y: Numeric values to append/replace the live series.
- layout: Optional partial layout updates; can be empty `{}`.

The client script tries to extend existing traces by name, falling back to `Plotly.react` if needed.

## Running a mock server

A tiny HTTP server is included for local testing:

- Script: `scripts/mock_live_updates.py`
- Default endpoint: `http://127.0.0.1:9109/live`

Example (PowerShell):

```
python scripts/mock_live_updates.py --port 9109 --pairs NIFTY:this_week:ATM --pairs BANKNIFTY:this_week:ATM --interval 1.0
```

- `--pairs` corresponds to the panel ids you render (`INDEX:EXPIRY:OFFSET`).
- `--interval` controls the update cadence in seconds.

## Generating the overlays HTML with live polling

The plotting script accepts optional flags for live updates, theming, and statistical helpers:

```
python scripts/plot_weekday_overlays.py \
  --live-root data/g6_data \
  --weekday-root data/weekday_master \
  --index NIFTY --expiry-tag this_week --offset ATM \
  --layout grid \
  --live-endpoint http://127.0.0.1:9109/live --live-interval-ms 1000 \
  --theme dark --enable-zscore --enable-bands --bands-multiplier 2.0 \
  --output overlays_demo.html
```

Open `overlays_demo.html` in your browser. The page will:
- Load the plot from static CSVs
- Apply the selected theme (persisted via localStorage)
- Poll the endpoint to update live series

## Controlling the Plotly bundle

The HTML includes Plotly via a resolver (`src.utils.assets.get_plotly_js_src()`):
- Env override: `G6_PLOTLY_JS_PATH`
- Fallback to local `src/assets/js/plotly.min.js` if present
- Otherwise use a pinned CDN version (env `G6_PLOTLY_VERSION`, default 2.26.0)

This ensures deterministic behavior in CI and when sharing HTML artifacts.

## Notes

- Live updates are optional; if you omit `--live-endpoint` the page renders static overlays only.
- Z-score and bands are computed client-side from the rendered series; they’re behind flags to keep defaults unchanged.
- PNG export is supported if `kaleido` is installed (`--static-dir <dir>`), otherwise it’s silently disabled after first failure.
