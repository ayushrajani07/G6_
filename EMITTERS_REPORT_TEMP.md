# G6 Output Router and Sinks

This is a lightweight, unified output interface for the platform. It centralizes
logging/printing/JSONL emission so you can produce structured events once and send
them to multiple destinations (stdout, Python logging, Rich console, JSONL files, or memory for tests).

## Quick start

- Import the global router from utils:

  ```python
  from src.utils import get_output
  out = get_output()
  out.info("Collector started", scope="collector", tags=["NIFTY"])  
  out.error("Provider failed", scope="provider", data={"reason": "timeout"})
  ```

- Configure sinks/level via env:
  - `G6_OUTPUT_SINKS` (csv of: `stdout,logging,rich,jsonl,memory`)
  - `G6_OUTPUT_LEVEL` (one of: `debug,info,warning,error,critical`)
  - `G6_OUTPUT_JSONL_PATH` (used when `jsonl` sink is selected)

Defaults: `G6_OUTPUT_SINKS=stdout,logging`, `G6_OUTPUT_LEVEL=info`.

## Sinks

- StdoutSink: human-readable, compact lines to stdout.
- LoggingSink: forwards to the `g6` logger (`logging`), respecting your handlers.
- RichSink: colorful console output when `rich` is available; otherwise no-op.
- JsonlSink: appends structured JSON per line to a file.
- MemorySink: collects events in-memory (testing/dev tools).

## Data model

Each event is represented by `OutputEvent` with fields:
- `timestamp` (ISO UTC), `level`, `message`
- Optional: `scope`, `tags`, `data`, `extra`

## Summarizer integration

The summarizer (“summary_view.py”) already uses the router via `get_output()` to report startup/stop/errors.

Additionally, the Indices panel can now parse per-index collection stats (Legs/Fails/Status) from a terminal log file.

- Set `G6_INDICES_PANEL_LOG` to the path of your daily options collection output (the file that contains lines like:
  `NIFTY TOTAL LEGS: 272 | FAILS: 0 | STATUS: OK`).
- If not set, the summarizer will try `g6_platform.log` as a fallback.

The panel merges these metrics with the status snapshot LTP/Age so you see collection progress side-by-side with market data.

## Tests

See `tests/test_output_router.py` for examples that cover:
- In-memory sink collection
- Level filtering
- Stdout formatting
- JSONL persistence
- Router factory from env

## Tips

- Use `get_output(reset=True)` in tests to re-create the router with new env.
- Prefer the router over direct `print`/`logging` to keep a single consistent pipeline.

## Panels sink (per-panel JSON files)

Enable a sink that writes panel snapshots to JSON files for the summarizer to stream later.

1) Configure env:
   - `G6_OUTPUT_SINKS=stdout,logging,panels`
   - `G6_PANELS_DIR=data/panels`
   - Optionally restrict: `G6_PANELS_INCLUDE=indices,market,loop`
   - Atomic replace (Windows-friendly) is on by default: `G6_PANELS_ATOMIC=true`

2) Emit panel updates from code:

```python
from src.utils import get_output
out = get_output()
out.panel_update("indices", {
  "NIFTY": {"legs": 272, "fails": 0, "status": "OK"},
  "BANKNIFTY": {"legs": 84, "fails": 0, "status": "OK"},
})
```

This writes `data/panels/indices.json` with a stable schema including `updated_at` and `kind` (optional).

### Summarizer preference for panels JSON

The summarizer (`scripts/summary_view.py`) now prefers reading per-panel JSON files when available.

- Toggle with `G6_SUMMARY_READ_PANELS` (default: true)
- Directory configurable via `G6_PANELS_DIR` (default: `data/panels`)
- Panels read: `indices, market, loop, provider, health, sinks, resources, analytics, alerts, links`
- Graceful fallback: if a file is missing or malformed, the summarizer falls back to fields in the status snapshot, and for Indices metrics ultimately to terminal log parsing when configured.

This creates a clean, file-based bridge: your runtime can emit snapshots to per-panel files using the router (`out.panel_update(...)`), and the summarizer will display them immediately without having to embed the same data into the monolithic status JSON.
# Terminal Output Emitters (Temporary Report)

This temporary report aggregates likely terminal output sources across the repository. Categories:
- print: direct Python print()
- rich: Rich console prints (console.print / rprint)
- logging: logger/logging calls (info/warning/error/debug/critical/exception)
- other: sys.stdout.write/sys.stderr.write, click.echo, warnings.warn, Rich Console.log

Note: Line numbers are approximate and may drift as files change. Searches were capped at 200 results in some files; there may be additional matches.

## Summary by category
- print: many matches in src/ and scripts/ (utilities and CLI tools)
- rich: primarily in scripts/terminal_dashboard.py, dashboard_live.py, monitor_status.py
- logging: pervasive in core src/ modules (unified_main.py, main.py, collectors, providers, storage, metrics, tools/token_manager.py, health)
- other: minimal usage found (sys.stdout.write in token_manager)

---

## Detailed matches

### 1) Direct print() calls

Top files with prints (examples only; not exhaustive due to cap):

- src/debug_mode.py: 31, 35, 40, 43, 45, 65, 67, 70, 79, 80, 82
- src/direct_collect.py: 17
- src/test_all_indices.py: 16
- src/test_expiries.py: 15
- src/tools/check_imports.py: 18, 21, 26, 57
- src/tools/check_kite_file.py: 14, 17, 23-28, 31, 33
- src/tools/create_config.py: 56
- src/tools/run_with_real_api.py: 27, 34
- src/tools/token_manager.py: 136-141, 219-220, 320-325, 334, 344, 382-387, 392, 394, 397-398, 404, 438, 460-462, 479-484, 492, 523, 527, 533-534
- src/ui_enhanced/dashboard_stub.py: 16, 21
- src/console/terminal.py: 130
- src/utils/circuit_breaker.py: 162, 164, 166, 171, 173

- scripts/diagnose_expiries.py: 15, 17, 19, 24, 26
- scripts/inspect_options_snapshot.py: 77, 79, 81, 83
- scripts/weekday_overlay.py: 78, 114, 206, 226, 232, 234
- scripts/plot_weekday_overlays.py: 87-88, 187, 366-367
- scripts/generate_overlay_layout_samples.py: 139
- scripts/terminal_dashboard.py: 247-253
- scripts/quick_provider_check.py: 14, 27-28, 30, 38, 40, 42, 47, 49
- scripts/monitor_status.py: 68, 78, 85, 88
- scripts/dashboard_live.py: 105
- scripts/ci_time_guard.py: 45, 47, 49, 51, 53
- scripts/mock_run_once.py: 58, 60
- scripts/status_viewer.py: 49, 57, 60, 62-63, 67, 70
- scripts/dev_tools.py: 77, 79, 89, 99, 101, 116, 120, 122, 124, 133, 137
- scripts/benchmark_cycles.py: 90, 92
- scripts/smoke_dummy.py: 97

- tests/test_cli_validate_status_optional.py: 27-28

### 2) Rich console prints

- scripts/terminal_dashboard.py: 513, 515, 520, 522, 525, 527, 539, 541, 543, 546, 559, 564, 571, 573, 575, 589, 591, 593, 596
- scripts/monitor_status.py: 56 (console.print)
- scripts/dashboard_live.py: 117 (console.print), 127 (rprint)

### 3) Logging emitters (logger/logging/log.*)
Examples by module (line numbers show presence; many more within each module):

- src/unified_main.py: 97, 122, 124, 193, 224, 269, 273, 276, 278, 280, 282, 284, 325, 330-331, 432, 440, 442, 444, 593, 645, 648, 661, 689, 700, 703-704, 706, 708, 711, 722, 729, 769, 776, 782, 788, 811-816, 818, 825, 827-828, 835, 871, 873, 887, 911, 941, 946, 970, 972, 1006, 1008, 1020, 1022, 1045, 1068, 1089
- src/main.py: 79, 84, 92, 94, 102, 104, 108-109, 146, 152, 193, 196, 199, 272, 274, 300, 303, 337, 386, 390, 403-404, 420, 438, 447, 474, 476, 482, 494, 503, 516-517, 538, 541, 545, 552, 563, 586, 599, 605, 610, 621, 626, 632
- src/collectors/unified_collectors.py: 24, 72, 82, 90, 92, 99, 101, 109, 125, 134, 136, 166, 168, 176, 205, 222, 224, 250, 252, 261, 272, 329, 342, 344, 383, 386, 392, 394, 417, 442, 450, 475, 479, 481, 507, 516, 526, 528, 559, 587, 589, 607, 609, 633, 638, 640, 642, 704, 722, 727, 729, 732, 734, 736
- src/collectors/providers_interface.py: 17, 46, 86, 90, 92, 100, 102, 107, 113, 119, 121, 124, 128, 154-155, 157-158, 163, 175, 190, 210, 221, 231, 245, 261, 271, 275, 280, 299, 308, 314, 320, 336, 341, 364, 409
- src/storage/csv_sink.py: 35-36, 84, 94, 96, 124, 126, 180, 217, 249, 251, 382, 472, 552, 554, 584, 607, 641, 682
- src/storage/influx_sink.py: 16, 49, 51, 53, 60, 62, 98, 151, 154, 163, 171, 224, 227, 234, 279, 287
- src/metrics/metrics.py: 19, 50, 55, 191, 196, 234, 398, 403, 416, 418, 438-442, 451, 480, 485, 487, 528, 533, 535
- src/broker/kite_provider.py: 15, 29, 76, 83, 99, 104, 129, 168, 203, 247, 308-319, 330, 334, 336-337, 355, 363, 372, 388, 418, 436, 451, 460, 498-504, 524, 534, 613, 630-634, 638-639, 644, 659, 663, 927
- src/tools/token_manager.py: 33-42, 48, 51, 72, 83, 87, 91, 110, 122, 130-131, 146, 170, 182, 193, 198, 218, 296, 317, 348, 358, 408, 414, 420, 429, 459, 466, 470, 491, 496, 503, 508, 516, 541
- src/config/config_loader.py: 14, 45, 57, 64, 68, 71
- src/health/health_checker.py: 31, 66, 70; src/health/monitor.py: 16, 34, 56, 73, 84, 91, 101, 130, 133, 136, 157, 159, 162, 204
- src/utils/bootstrap.py: 50, 80, 82; src/utils/logging_utils.py: 14-15, 24-25, 43, 45, 49, 53, 65, 68, 74
- src/utils/*: resilience.py 13, 54, 62, 92; memory_pressure.py 16, 101, 110, 163, 196, 201, 224; rate_limiter.py 7, 36, 41; data_quality.py 11, 18
- src/analytics/*: option_chain.py 16, 64, 66, 68, 84, 151, 166, 201, 216, 272; option_greeks.py 29, 146; redis_cache.py 34, 61, 80, 83, 119, 142, 159, 176, 221, 250, 266
- src/tools/test_kite_connection.py: 22, 26, 35, 45, 50, 69, 75, 78-79, 81, 83

### 4) Other emitters

- sys.stdout.write():
	- src/tools/token_manager.py: 341
- sys.stderr.write(): none found
- click.echo(): none found
- warnings.warn(): none found
- Rich Console.log(): none found

### Notes
- Some searches were result-capped; additional emitters may exist in the same files.
- This report is intentionally non-invasive: no code changes were made.
- If you want this list exported as JSON for tooling, say "export JSON" and I’ll generate a machine-readable version next.

---

## Unified Output Router (new)

A small helper has been added to centralize emissions across stdout/logging/Rich/JSONL:

- Import: `from src.utils import get_output`
- Usage:
  - `out = get_output()`
  - `out.info("Message", scope="module.function", tags=["phase:init"], data={"k": "v"})`
- Config via env:
  - `G6_OUTPUT_SINKS`: comma list of sinks: stdout, logging, rich, jsonl, memory
  - `G6_OUTPUT_LEVEL`: min level (debug|info|warning|error|critical)
  - `G6_OUTPUT_JSONL_PATH`: file path for jsonl sink

Keep existing emitters unchanged for now; migrate opportunistically where flexible routing is desired.
