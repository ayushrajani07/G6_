# G6 Options Trading Platform - Deployment Guide

## 🎯 Reorganization Complete

Your G6 platform has been successfully reorganized with all critical issues resolved:

### ✅ Fixed Issues
- **Import conflicts**: All modules now have proper `__init__.py` files and clean import paths
- **Class name conflicts**: Standardized on `CsvSink` throughout the platform  
- **Function signature mismatches**: All interfaces aligned between collectors and storage
- **Schema typos**: Fixed `call_avgerage_price` → `call_average_price`
- **Path resolution**: Always includes offset in directory structure
- **Configuration chaos**: Consolidated to JSON-first with minimal environment variables
- **Metrics redundancy**: Single metrics registry replaces multiple implementations
- **Provider placeholders**: Real Kite Connect integration with production-ready features

## 📁 New Structure

```
g6_reorganized/
├── main.py                    # Merged main app + Kite integration
├── config/
│   ├── config_loader.py       # Consolidated configuration system
│   ├── g6_config.json        # Main configuration file
│   └── environment.template   # Authentication secrets template
├── collectors/
│   └── collector.py           # Fixed data collection with proper interfaces
├── storage/
│   ├── csv_sink.py           # CSV storage with offset-based paths
│   └── influx_sink.py        # InfluxDB storage with corrected schema
├── providers/
│   └── kite_provider.py      # (Create wrapper if needed)
├── orchestrator/
│   └── orchestrator.py       # (To be created if needed)
├── metrics/
│   └── metrics.py            # Consolidated Prometheus metrics
├── analytics/
│   └── redis_cache.py        # Redis caching with fallback
└── utils/
    └── timeutils.py          # Market hours and timezone utilities
```

## 🚀 Quick Start

### 1. Set Up Environment
```bash
# Copy and customize environment variables
cp g6_reorganized/config/environment.template .env
# Edit .env with your actual Kite Connect credentials:
# KITE_API_KEY=your_actual_api_key
# KITE_ACCESS_TOKEN=your_actual_access_token
# INFLUX_TOKEN=your_influx_token (if using InfluxDB)
```

### 2. Install Dependencies
```bash
pip install kiteconnect influxdb-client prometheus-client redis orjson tenacity filelock pytz
```

### 3. Customize Configuration
Edit `g6_reorganized/config/g6_config.json`:
- Adjust `index_params` for your target indices
- Configure storage paths and InfluxDB settings
- Set market hours and collection intervals

### 4. Run the Platform
```bash
cd g6_reorganized
export $(cat ../.env | xargs)  # Load environment variables
python main.py
```

## 🔧 Configuration Details

### Main Configuration (`g6_config.json`)
- **Storage**: CSV directory, InfluxDB connection settings
- **Kite**: API rate limits, caching, retry logic  
- **Orchestration**: Collection intervals, logging, metrics port
- **Index Parameters**: Strike steps, expiry rules, offsets per index

### Environment Variables (Authentication Only)
- `KITE_API_KEY`: Your Kite Connect API key
- `KITE_ACCESS_TOKEN`: Your access token
- `INFLUX_TOKEN`: InfluxDB authentication token

### Logging / Output Control Environment Variables
- `G6_CONCISE_LOGS` – Enables concise log mode (default: enabled unless explicitly set to 0/false) which suppresses verbose per-strike dumps.
- `G6_CYCLE_OUTPUT` – Controls which cycle summary line(s) are emitted each collection cycle. Values:
   - `pretty` (default) – Emit only the human-readable `CYCLE_SUMMARY` line (noise minimized).
   - `raw` – Emit only the machine-parseable `CYCLE` key=value line (for legacy parsers / ingestion scripts).
   - `both` – Emit both lines (raw first, then pretty) during migration to the new format.
   If the legacy variable `G6_DISABLE_PRETTY_CYCLE` is set truthy (`1/true/yes/on`), it forces `raw` behavior regardless of `G6_CYCLE_OUTPUT` for backward compatibility.

#### Additional Noise Reduction (Automatic under Concise Mode)
When `G6_CONCISE_LOGS` is ON (default):
- Index spot / OHLC lines ("Index data for ...") become DEBUG.
- LTP / ATM strike lines become DEBUG.
- EXPIRIES summaries become DEBUG.
- OPTIONS summaries become DEBUG.
- Per-expiry CSV "Data written" lines become DEBUG.
- Aggregated overview snapshot lines become DEBUG.
- Structured per-index `INDEX ...` lines become DEBUG (human table & cycle summary remain at INFO).

To temporarily restore previous verbosity without changing code set:
```
G6_CONCISE_LOGS=0
```
Or selectively raise log level for a module via standard logging config.

Legacy variable retained:
- `G6_DISABLE_PRETTY_CYCLE` – Legacy override to suppress pretty summary; prefer `G6_CYCLE_OUTPUT=raw` moving forward.

### Colorized Output
ANSI color is automatically enabled for TTY terminals. Control with:
`G6_COLOR` values:
   - `0,false,off` – disable colors
   - `1,true,on,force` – force enable colors even if not a TTY
   - `auto` (default) – enable only when stdout is a TTY

Health component and custom health check lines print in green when healthy and red/bold when failing. Cycle summary status column colors: green OK, yellow DEGRADED, red STALL/NO_DATA, magenta for other anomalous states.

### Startup Banner
On launch a condensed startup banner summarizing indices, interval, components, and health check statuses is emitted. Disable via:
```
G6_DISABLE_STARTUP_BANNER=1
```
To revert to legacy verbose startup (also disable colors):
```
G6_DISABLE_STARTUP_BANNER=1
G6_COLOR=0
```

## 📊 Monitoring

- **Prometheus Metrics**: Available at `http://localhost:9108/metrics`
- **Logs**: Written to `g6_platform.log`
- **Health Checks**: Built into all major components

## 🔍 Data Output

### CSV Files (with offset paths)
```
data/csv/overview/NIFTY/this_week/0/2025-09-02.csv
data/csv/options/NIFTY/this_week/1/2025-09-02.csv
```

### InfluxDB Measurements
- `overview`: Index spot prices, OHLC, volume, OI
- `options`: Options chain with call/put premiums, volume, OI
- Tags: `index`, `expiry_code`, `offset`, `dte`

## 🛠️ Key Features

### Production-Ready Components
- **Rate limiting**: Respects Kite Connect API limits
- **Caching**: Intelligent instrument caching with TTL
- **Error handling**: Graceful degradation and retry logic
- **Monitoring**: Comprehensive Prometheus metrics
- **Logging**: Structured logging with proper levels

### Market-Aware Operation
- **Market hours detection**: Automatic IST timezone handling
- **Expiry resolution**: Smart weekly/monthly expiry logic
- **ATM strike calculation**: Index-specific strike rounding
- **Offset-based collection**: Configurable strike offsets per index

## 🔧 Troubleshooting

### Common Issues
1. **Import Errors**: Ensure you're running from `g6_reorganized/` directory
2. **Kite Authentication**: Check environment variables and token validity
3. **InfluxDB Connection**: Verify InfluxDB is running and token is correct
4. **Permissions**: Ensure write access to data directories

### Health Checks
```python
# Check component health
from metrics.metrics import get_metrics_registry
registry = get_metrics_registry()
# View at http://localhost:9108/metrics
```

## 📈 Performance Optimizations

- **Batch API calls**: Optimized request batching for Kite API
- **Concurrent collection**: Parallel processing per index
- **Memory management**: Efficient data structures and caching
- **File locking**: Safe concurrent CSV writing

## 🔄 Migration from Original G6

1. **Backup existing data**: Copy your current `data/` directory
2. **Update imports**: Use new module structure if integrating custom code  
3. **Configuration**: Convert old config files using the new schema
4. **Test thoroughly**: Run in development before production deployment

## 📚 Next Steps

1. **Phase 3: Documentation & Testing**
   - Comprehensive API documentation
   - Unit tests for critical components
   - Integration tests with mock data
   - Performance benchmarks

2. **Production Deployment**
   - Docker containerization
   - Process monitoring (systemd/supervisor)
   - Log rotation and archival
   - Database maintenance scripts

Your G6 platform is now production-ready with robust error handling, monitoring, and scalable architecture! 🎉

---

## 🌍 Timezone & UTC Standardization

All persisted / cross-process timestamps are now standardized to UTC and emitted in ISO-8601 format with a `Z` suffix (e.g. `2025-09-16T09:35:27.184203Z`). This avoids ambiguity around local time vs exchange time and simplifies downstream aggregation in time-series databases, dashboards, and alerting.

### Helper Functions (`src.utils.timeutils`)
| Helper | Purpose |
|--------|---------|
| `utc_now()` | Returns a timezone-aware `datetime` in UTC. |
| `isoformat_z(dt)` | Serializes a UTC `datetime` to ISO string with trailing `Z`. |

Example:
```python
from src.utils.timeutils import utc_now, isoformat_z
stamp = isoformat_z(utc_now())  # '2025-09-16T09:35:27.184203Z'
```

### When to Use UTC vs Local (IST)
Use UTC for:
- Runtime status file (`--runtime-status-file`)
- InfluxDB points (cycle stats, overview, options)
- Redis / cache metadata timestamps
- Health / monitoring JSON sidecars

Use localized (IST) display strings only for human-facing console summaries where traders expect local market time context. These are clearly labeled and not reused for persistence.

### Migration Notes
Residual `datetime.utcnow()` usages have been replaced with `utc_now()` (with a conservative fallback inside isolated try/except blocks). Any future additions should import the helper instead of calling `datetime.utcnow()` directly.

### Validation
A dedicated test (`test_status_timestamp_tz.py`) asserts the runtime status timestamp ends with `Z`. If you add a new persisted timestamp field, mirror that test pattern or extend it.

### Rationale
Naive datetimes (`datetime.utcnow()`) lack timezone info, leading to accidental mixing of naive + aware objects and inconsistent serialization. Standardizing on aware UTC objects prevents subtle bugs (especially around DST boundaries) and ensures consistent ordering when data is ingested by external systems.

If a module loads before helpers (rare in edge bootstrap scripts), minimal fallback shims are used and later replaced once imports succeed—this prevents early-start failures without compromising the policy.

---

## 🔄 Updated Entrypoint Strategy (Unified)

The legacy `src.main` has been replaced by `src.unified_main`, which consolidates basic and advanced collection flows, health monitoring, metrics, analytics, and token pre-validation.

Primary ways to run:

1. Direct (recommended for automation):
   ```bash
   python scripts/run_orchestrator_loop.py --validate-auth --run-once
   ```
2. With automatic token acquisition (opens browser if needed) via token manager then orchestrator:
   ```bash
   python -m src.tools.token_manager -- --validate-auth --run-once
   ```
3. Token Manager interactive helper examples:
   ```bash
   # Validate/acquire token then prompt
   python -m src.tools.token_manager --no-autorun
   # Validate and launch orchestrator (pass extra flags after --)
   python -m src.tools.token_manager -- --validate-auth --run-once --analytics
   ```

## 🔐 Token Lifecycle & Manager

The token manager (`src.tools.token_manager`) provides:
- Validation of existing `KITE_ACCESS_TOKEN`
- Automated browser-based login (Flask callback)
- Guided manual refresh flow
- Manual token entry fallback
- Pass-through execution of the unified platform

Helper function `acquire_or_refresh_token()` is used internally by `--auto-refresh-token` logic.

Environment essentials:
```
KITE_API_KEY=xxxxx
KITE_API_SECRET=yyyyy
KITE_ACCESS_TOKEN=zzzzz   # refreshed daily after login
```

## 🏁 CLI Flags (Unified Main)

| Flag | Purpose | Typical Use |
|------|---------|-------------|
| `--validate-auth` | Fail fast if provider cannot return a valid LTP | CI / health probe |
| `--auto-refresh-token` | Attempt programmatic token acquisition before init | Morning startup |
| `--interactive-token` | Allow fallback guided/manual acquisition | Desktop run |
| `--run-once` | Execute a single collection cycle then exit | Smoke tests |
| `--use-enhanced` | Use enhanced collectors variant | Advanced mode |
| `--analytics` | Run analytics block (PCR, max pain, SR) at startup | Ad-hoc insight |
| `--market-hours-only` | Sleep outside market hours | Continuous daemon |
| `--interval N` | Override collection interval seconds | Tuning |
| `--log-level LEVEL` | Adjust verbosity | Debugging |

### Pass-Through via Token Manager

Anything after `--` is forwarded to the orchestrator runner:
```bash
python -m src.tools.token_manager -- --validate-auth --run-once --analytics
```

### Common Recipes
```bash
# Quick validity & one cycle
python scripts/run_orchestrator_loop.py --validate-auth --run-once

# Morning start with automatic token refresh
python -m src.tools.token_manager -- --auto-refresh-token --interactive-token --market-hours-only

# Smoke test with dummy provider (configure provider type in config)
python scripts/run_orchestrator_loop.py --config config/g6_config.json --run-once
```

## 🧪 Smoke & Diagnostic Modes

To validate without real API risk, set provider type to dummy in config and run a single cycle.

## 🖥️ Terminal Attach Mode & Runtime Status

The platform can periodically write a structured JSON snapshot each collection cycle. A lightweight Rich-based terminal UI (in `src/console/terminal.py`) or any external watcher can consume this file to render live dashboards without modifying the core runtime.

### Enable Runtime Status Output

Precedence for choosing the status file path:
1. CLI flag: `--runtime-status-file <path>`
2. Environment: `G6_RUNTIME_STATUS=<path>`
3. Config: `console.runtime_status_file` (if added to `g6_config.json`)

Example run (writes status each cycle):
```bash
python scripts/run_orchestrator_loop.py --runtime-status-file data/runtime_status.json
```

Example JSON fields (subject to extension):
```json
{
  "timestamp": "2025-09-16T07:15:31.842Z",
  "cycle": 12,
  "elapsed": 1.237,
  "interval": 60,
  "sleep_sec": 58.763,
  "success_rate_pct": 100.0,
  "options_last_cycle": 420,
  "options_per_minute": 410.3,
  "api_success_rate": 0.995,
  "memory_mb": 142.6,
  "cpu_pct": 12.4,
  "readiness_ok": true,
  "readiness_reason": "LTP=20012.5",
   "indices": ["NIFTY","BANKNIFTY"],
   "indices_info": {
      "NIFTY": {"ltp": 20015.25},
      "BANKNIFTY": {"ltp": 45012.40}
   }
}
```

Atomic write behavior: file is first written to `<path>.tmp` then moved into place to avoid partial reads.

### Attach Terminal Mode (Rich Logging)
Set `G6_TERMINAL_MODE=attach` before launching to add a Rich console handler (color + nice formatting) without altering existing log file output.
```bash
G6_TERMINAL_MODE=attach python scripts/run_orchestrator_loop.py --runtime-status-file data/runtime_status.json
```

You can build your own custom viewer or extend `src/console/terminal.py` to periodically read and render the JSON.

### Rich Live Dashboard Script

Included helper: terminal summary

```powershell
python -m scripts.summary.app --refresh 1.0
```
Panels JSON artifacts are generated in-process (no external bridge required). The summary auto-detects panels mode when `data/panels/` exists (deprecated env vars `G6_SUMMARY_PANELS_MODE` / `G6_SUMMARY_READ_PANELS` have been removed; remove them from any deployment scripts).

### Per-Index Option Counts (Upgrade)

The `indices_info` object now contains an `options` field that reflects the real number of option rows processed for that index in the most recently completed cycle. Implementation details:

- During collection each index aggregates its per-expiry option rows; the total is stored into an internal map `metrics._per_index_last_cycle_options`.
- The runtime status writer accesses this map to populate `indices_info[INDEX].options`.
- If a cycle has not yet populated a particular index (rare early startup race) the value may be `null` or fall back to the aggregate `options_last_cycle`.
- Prometheus still exposes `g6_index_options_processed{index=...}` (last cycle) and `g6_index_options_processed_total{index=...}` (monotonic cumulative).

Example snippet (extended):
```json
"indices_info": {
   "NIFTY": { "ltp": 20015.25, "options": 420 },
   "BANKNIFTY": { "ltp": 45012.40, "options": 388 }
}
```

Use cases:
- Drive per-index sparklines / trend buffers.
- Detect stalls isolated to a single index (when total options processed still moves due to others).

Future roadmap: retention of a short rolling history per index to support inline small charts in terminal/WebSocket consumers.

## 🔌 WebSocket / HTTP Status Service (Optional)

For remote or multi-client dashboards you can run the lightweight FastAPI service that streams status updates.

Start service (PowerShell helper):
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_ws_service.ps1 -StatusFile data\runtime_status.json -Port 8765
```

Or directly with uvicorn:
```bash
STATUS_FILE=data/runtime_status.json uvicorn src.console.ws_service:app --host 0.0.0.0 --port 8765
```

Endpoints:
- `GET /`         -> basic service info
- `GET /status`   -> latest JSON snapshot
- `WS  /ws`       -> real-time push (sends latest on connect; pushes when file mtime changes)

Example Python WebSocket client:
```python
import asyncio, json, websockets
async def run():
   async with websockets.connect('ws://localhost:8765/ws') as ws:
      while True:
         msg = await ws.recv()
         data = json.loads(msg)
         print('Cycle', data['cycle'], 'Success', data.get('success_rate_pct'))
asyncio.run(run())
```

When to use:
- Multiple remote viewers
- Sub-second latency needs
- Planning future interactive commands (control channel)

Otherwise polling the status file or using the Rich dashboard is sufficient.

## 🧪 Mock Data Provider (Offline / Off-Market Development)

A synthetic provider is built-in for quick development, demos, or running outside market hours—no Kite credentials required.

Enable via either:
```bash
python -m src.unified_main --mock-data --runtime-status-file data/runtime_status.json
# or
G6_USE_MOCK_PROVIDER=1 python -m src.unified_main --runtime-status-file data/runtime_status.json
```

## 📈 InfluxDB Cycle Metrics (New)

If Influx is enabled in configuration, each completed collection cycle now emits a lightweight measurement `g6_cycle` with core performance signals.

Measurement: `g6_cycle`
- Fields:
   - `cycle` (int) sequential cycle counter
   - `elapsed_seconds` (float) wall time for the cycle
   - `success_rate_pct` (float) aggregate success percentage over lifetime so far
   - `options_last_cycle` (int) total option rows processed in the cycle
   - `options_<INDEX>` (int) per-index option counts (e.g., `options_NIFTY`)

Use cases:
- Grafana single-stat / sparkline for cycle latency
- Detect index-specific stalls while aggregate still moves
- Correlate spikes in `elapsed_seconds` with drops in per-index throughput

Retention Tip: This measurement is low cardinality (no tags today). Safe for moderate retention windows (e.g., 14-30 days) without large storage footprint.

Disable: Omit or set `influx.enable=false` in config; writer is a no-op when Influx is disabled or client initialization fails.

Behavior:
- Generates smooth sinusoidal LTP values around stable base levels (NIFTY, BANKNIFTY, FINNIFTY, SENSEX)
- Provides minimal `get_ltp`, `get_quote`, and naive weekly expiry resolution
- Skips the Kite authentication/token acquisition phase entirely

When active you will see a startup log:
```
[MOCK] Using synthetic MockProvider (no external API calls / auth).
```

Use cases:
- UI development before market open
- Local performance profiling without rate limits
- Smoke tests in CI where credentials are unavailable

Limitations:
- No options chain; only index LTP-style data is meaningful
- Expiry resolution is approximate (next Thursday)
- Do not rely on values for analytics or trading decisions

## 🔍 Quick Monitor Helper

You can build a tiny watcher script to pretty-print status deltas:
```python
import json, time, os, datetime
PATH = 'data/runtime_status.json'
last_cycle = -1
while True:
   try:
      with open(PATH) as f:
         data = json.load(f)
      if data['cycle'] != last_cycle:
         last_cycle = data['cycle']
         print(f"[{data['cycle']}] {data['timestamp']} LTP readiness={data.get('readiness_ok')} success={data.get('success_rate_pct')}% options={data.get('options_last_cycle')}")
   except FileNotFoundError:
      pass
   except Exception as e:
      print('error:', e)
   time.sleep(1)
```
Add refinements as needed (color, Rich, curses, etc.).

---

## 🩺 Health & Metrics Quick Check
```bash
curl -s http://localhost:9108/metrics | head
```
If `primary_provider_responsive` reports unhealthy: refresh token or check network.

## 🧵 Graceful Shutdown Behavior

Ctrl+C now results in exit code 0 (clean) from token_manager; unified_main handles signal and closes providers, health monitor, and metrics server.

## 📆 Expiry Resolution Roadmap

Planned refinements (see todo):
1. Cache per-exchange instrument lists with TTL & selective filtering.
2. Maintain a lightweight expiry index file in `data/state/expiries.json` with last refresh timestamps.
3. Reduce ATM-centered instrument filtering window dynamically (strike ± range based on index volatility).
4. Add `--refresh-expiries` CLI flag to force cache invalidation.
5. Provide metrics: `g6_expiry_cache_hits`, `g6_expiry_cache_misses`.

## 🔄 Daily Operations Checklist

1. Refresh or validate token:
   ```bash
   python -m src.tools.token_manager --no-autorun
   ```
2. Start continuous collector:
   ```bash
   python -m src.unified_main --auto-refresh-token --interactive-token --market-hours-only
   ```
3. Spot check metrics & logs.
4. End of day: archive logs / rotate if needed.

## ❗ Troubleshooting Addendum

| Symptom | Likely Cause | Action |
|---------|--------------|--------|
| Immediate exit with auth error | Expired/invalid token | Run token manager refresh |
| Empty `index_params` warning | Config missing indices translation | Verify `indices` block or `index_params` | 
| Provider unhealthy in metrics | Network/API outage or token invalid | Revalidate with `--validate-auth` | 
| UnicodeEncodeError (resolved) | Legacy box-drawing chars | Already sanitized - update to latest code |

## 📘 Versioning Note

Unified entrypoint version: reported via `--version` as `G6 Unified 2.x`. Token manager remains backward-compatible but now launches unified_main only.

---
