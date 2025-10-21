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

## (Former) mock server

Historically a helper script `scripts/mock_live_updates.py` provided a throwaway HTTP endpoint for local demos.
It was removed on 2025-10-05 during surface reduction (unused in tests; zero coverage).

Replacement options:

1. Minimal ad-hoc server (example):
   ```python
   # quick_live_server.py
   import json, time, math, random
   from http.server import BaseHTTPRequestHandler, HTTPServer

   t0 = time.time(); series = []
   class H(BaseHTTPRequestHandler):
     def log_message(self, *a): pass
     def do_GET(self):  # noqa
       if self.path.startswith('/live'):
         now = time.time()
         y = 1000 + 100*math.sin((now-t0)/60) + random.uniform(-10,10)
         series.append((now,y)); series[:] = series[-600:]
         body = {"panels": {"panel-NIFTY-this_week-ATM": {
           "x": [time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(s[0])) for s in series],
           "y": [s[1] for s in series],
           "layout": {}
         }}}
         b = json.dumps(body).encode(); self.send_response(200)
         self.send_header('Content-Type','application/json'); self.end_headers(); self.wfile.write(b)
       else:
         self.send_response(404); self.end_headers()
   if __name__ == '__main__':
     HTTPServer(('127.0.0.1',9109), H).serve_forever()
   ```
   Run: `python quick_live_server.py` then add `--live-endpoint http://127.0.0.1:9109/live` to the overlays command.
2. Integrate real feed: Expose your production JSON using the same contract.
3. Skip live mode entirely (omit `--live-endpoint`).

The demo launcher `start_overlays_demo.ps1` now runs without a mock server by default; uncomment and supply your own endpoint to re-enable live polling.

## Generating the overlays HTML with live polling

The plotting script accepts optional flags for live updates, theming, and statistical helpers:

```
python scripts/plot_weekday_overlays.py \
  --live-root data/g6_data \
  --weekday-root data/weekday_master \
  --index NIFTY --expiry-tag this_week --offset 0 \
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
