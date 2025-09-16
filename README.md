# G6 Options Data Collection & Analytics Platform

## Overview
G6 is a modular options market data collection and analytics platform. It ingests option chain data for configured Indian indices (e.g. NIFTY, BANKNIFTY, FINNIFTY), computes derived analytics (PCR, Greeks, Implied Volatility), and persists snapshots to CSV and optionally InfluxDB for downstream analysis and visualization.

Core goals:
- Reliable periodic collection (minute‑level by default) gated by market hours
- Unified orchestration & health monitoring
- Backward‑compatible schema evolution (CSV + Influx)
- Optional local analytics: IV estimation (Newton–Raphson) + Black‑Scholes Greeks
- Aggregated overview snapshots (single row/point per index per cycle) with expiry completeness masks
- Extensible metrics (Prometheus) for observability

## Key Components
| Area | Path | Purpose |
|------|------|---------|
| Orchestrated entrypoint | `src/unified_main.py` | Unified runtime: providers, collectors, health, metrics |
| Collectors | `src/collectors/unified_collectors.py` | Standard minute cycle; IV & Greeks pipeline |
| Enhanced collectors | `src/collectors/enhanced_collector.py` | (Optional) advanced strategies |
| CSV Sink | `src/storage/csv_sink.py` | Persistent per-option rows & aggregated overview |
| Influx Sink | `src/storage/influx_sink.py` | Time‑series storage for option and overview points |
| Analytics (Greeks) | `src/analytics/option_greeks.py` | Black‑Scholes pricing, Greeks, IV solver |
| Metrics | `src/metrics/metrics.py` | Prometheus counters, gauges & summaries |
| Config wrapper | `src/config/config_wrapper.py` | Normalizes heterogeneous JSON schemas |
| Token tools | `src/tools/token_manager.py` | Kite token acquisition / refresh |

## Data Flow (Cycle)
1. Resolve market hours; skip if closed.
2. For each enabled index:
   - Resolve expiries (weekly/monthly rules).
   - Build strike list (ATM ± configured ITM/OTM spans).
   - Fetch instruments, enrich with quotes.
   - (Optional) Estimate IV for missing entries.
   - (Optional) Compute Greeks using existing/estimated IV.
   - Persist per-option snapshot (CSV + Influx).
   - Aggregate PCR per expiry → write one overview snapshot (CSV + Influx).
3. Update Prometheus metrics.

## Aggregated Overview Snapshot
Each index emits one overview record per cycle capturing:
- PCR per expiry bucket (`this_week`, `next_week`, `this_month`, `next_month`)
- `expiries_expected`, `expiries_collected`
- Bit masks: `expected_mask`, `collected_mask`, `missing_mask`
- `day_width` (span of trading day observed in quotes)

Bit map values:
```
this_week=1, next_week=2, this_month=4, next_month=8
```

## Greeks & IV Pipeline
Order of operations when enabled through JSON config `greeks` section:
1. IV Estimation (if `estimate_iv=true` & option lacks positive iv): Newton–Raphson with bounds `[iv_min, iv_max]` and tolerance `iv_precision`.
2. Greeks Computation (if `enabled=true`): delta, gamma, theta (per day), vega (per 1% vol), rho (per 1% rate) using Black‑Scholes.
3. Persistence: CSV columns (including `ce_rho` / `pe_rho`), Influx fields (iv, delta, gamma, theta, vega, rho).

## Configuration
All runtime analytics now controlled **only** via JSON config (CLI flags deprecated and ignored for greeks/IV).

Example `config/g6_config.json` excerpt:
```json
{
  "greeks": {
    "enabled": true,
    "estimate_iv": true,
    "risk_free_rate": 0.055,
    "iv_max_iterations": 150,
    "iv_min": 0.005,
    "iv_max": 3.0,
    "iv_precision": 1e-5
  },
  "index_params": {
    "NIFTY": {"expiries": ["this_week", "next_week"], "strikes_otm": 10, "strikes_itm": 10, "enable": true},
    "BANKNIFTY": {"expiries": ["this_week"], "strikes_otm": 10, "strikes_itm": 10, "enable": true}
  },
  "storage": {"influx": {"enabled": true, "url": "http://localhost:8086", "bucket": "g6_options", "org": "g6"}},
  "collection": {"interval_seconds": 60}
}
```

### Greeks Config Keys
| Key | Meaning | Default |
|-----|---------|---------|
| enabled | Compute Greeks locally | false |
| estimate_iv | Estimate IV when missing | false |
| risk_free_rate | Annual risk‑free rate (decimal) | 0.05 |
| iv_max_iterations | Newton iterations cap | 100 |
| iv_min | Lower bound on IV | 0.01 |
| iv_max | Upper bound on IV | 5.0 |
| iv_precision | Convergence tolerance (abs price diff) | 1e-5 |

## Prometheus Metrics (New / Key)
| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| g6_iv_estimation_success_total | Counter | index, expiry | Successful IV solves |
| g6_iv_estimation_failure_total | Counter | index, expiry | Failed/aborted IV solves |
| g6_iv_estimation_avg_iterations | Gauge | index, expiry | Avg iterations current cycle |
| g6_option_delta/gamma/theta/vega (field via Influx) | Gauge | index, expiry, strike, type | Greeks (if computed) |

## CSV Schema Highlights
Per-option row (subset):
```
timestamp,index,expiry,symbol,type,strike,index_price,last_price,oi,volume,iv,delta,gamma,theta,vega,rho
```
Call/Put grouping may produce columns like `ce_rho` / `pe_rho` when aggregated by strike side.

## Influx Measurements
- `option_data`: tags = index, expiry, symbol, type, strike; fields = price, oi, volume, iv, delta?, gamma?, theta?, vega?, rho?
- `options_overview`: single point per index cycle with PCR & masks.

## Running
Default config path: `config/g6_config.json` (auto-created if missing).
```
python -m src.unified_main
```
To use a different config:
```
python -m src.unified_main --config config/alt_config.json
```

## Migration Summary (See MIGRATION.md for details)
- Added overview aggregation (single row/point per cycle).
- Added expiry completeness masks (bit flags) & counts.
- Renamed ambiguous CSV columns (`strike`→`index_price` old mapping handled internally) and added rho persistence.
- Introduced IV solver & Greeks pipeline with JSON-driven config.
- Extended Influx option points with Greeks & rho.
- Added IV estimation metrics (success/fail/avg iterations).
- Deprecated CLI control of greeks/IV (must configure via JSON).

## Roadmap / Future Ideas
- Histogram of IV solver iterations
- Vol surface export / interpolation module
- Risk aggregation dashboards (portfolio Greeks) 
- Alerting hooks (latency, data quality anomalies)

## Observability & Console UX Update (2025)
The legacy embedded terminal dashboard script and the experimental FastAPI web dashboard have been **removed**. Rationale:
- Redundant with Prometheus + Grafana (preferred visualization path)
- Increased maintenance surface (templating, async server, extra dependencies)
- Added startup & live cycle rich console panels that cover quick in-terminal situational awareness without a browser

Retained: Prometheus metrics exposure (unchanged) & any Grafana provisioning you already use.

Removed code & deps: `scripts/terminal_dashboard.py`, `scripts/run_platform_with_dashboard.py`, `src/web/dashboard/*`, `fastapi`, `uvicorn`, `jinja2`.

### New / Relevant Environment Flags
| Variable | Effect | Default |
|----------|--------|---------|
| `G6_CONCISE_LOGS` | Suppress repetitive per-option / expiry chatter | true |
| `G6_VERBOSE_CONSOLE` | Force full log lines (overrides concise) | false |
| `G6_DISABLE_MINIMAL_CONSOLE` | Re-enable timestamp/level formatting in console (otherwise message-only) | false |
| `G6_COLOR` | Force-enable ANSI colors (auto-detect otherwise) | (auto) |
| `G6_FANCY_CONSOLE` | Show colorful startup summary panel | true (TTY) |
| `G6_DISABLE_STARTUP_BANNER` | Skip startup panel entirely | false |
| `G6_LIVE_PANEL` | Enable per-cycle dynamic performance/status panel | true (TTY) |

Console now defaults to a minimal (message-only) formatter for readability; structured detail still goes to log files if configured.

If you previously relied on the FastAPI dashboard, migrate to Grafana dashboards pointed at Prometheus / Influx metrics. The removed UI exposed no unique data beyond what metrics already provide.

### Migration Notes
No config changes required. You may safely remove any local process managers or scripts referencing the old dashboard modules. Ensure you uninstall orphaned packages if they remain in your environment.

---

## Troubleshooting
| Symptom | Possible Cause | Action |
|---------|----------------|--------|
| No Greeks fields in Influx | greeks.enabled false | Set `greeks.enabled` true in config |
| IV always defaulting to 0.25 in Greeks | `estimate_iv` disabled | Enable `greeks.estimate_iv` |
| Missing overview rows | Market closed or provider errors | Check logs & health metrics |
| Influx writes skipped | Influx disabled or client import missing | Enable `storage.influx.enabled` and install `influxdb-client` |

## License
Internal / Proprietary (adjust as appropriate).
