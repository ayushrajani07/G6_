# G6 Feature & Console Toggles

This document explains how to enable analytics, the fancy startup panel, and the live per‑cycle panel.

For a comprehensive alphabetical catalog of all environment variables (including expiry service, adaptive scaling, HTTP, metrics and more) see `env_dict.md`.

## Precedence Rules
For each feature the order of precedence (highest wins) is:
1. CLI flag (where applicable)
2. Environment variable (explicit 1/true/yes/on)
3. JSON config key (`config/g6_config.json`)
4. Built-in default (shown below)

## Analytics Block at Startup
The analytics block (PCR, Max Pain, Support/Resistance) runs once immediately after health monitor start.

Ways to enable:
- Config: set `features.analytics_startup` to `true`
- CLI: add `--analytics` (overrides config)

Config snippet:
```json
"features": { "analytics_startup": true }
```

Verification: look for log lines starting with `Analytics NIFTY PCR:` after startup.

## Fancy Startup Panel
A rich, multi-line colored startup panel replacing the simple banner.

Ways to enable:
- Env: `G6_FANCY_CONSOLE=1`
- Config: `console.fancy_startup=true`

Disable banner entirely:
- Env: `G6_DISABLE_STARTUP_BANNER=1`
- Config: `console.startup_banner=false`

If disabled, neither fancy nor simple banner prints (other logs still appear).

## Live Panel (Per-Cycle Runtime Box)
Displays cycle timing, success %, throughput, API stats, memory, CPU, etc.

Ways to enable:
- Env: `G6_LIVE_PANEL=1`
- Config: `console.live_panel=true`

Appears once per collection cycle after collectors finish; does not show on `--run-once` beyond that single cycle.

## Example Consolidated Config Block
```json
{
  "features": { "analytics_startup": true },
  "console": {
    "fancy_startup": true,
    "live_panel": true,
    "startup_banner": true
  }
}
```

## Quick Start Commands (PowerShell)
Enable all via environment (highest precedence):
```powershell
$env:G6_FANCY_CONSOLE=1; $env:G6_LIVE_PANEL=1; python scripts/run_orchestrator_loop.py --config config/g6_config.json --analytics
```

Using only config (remove env vars):
1. Edit `config/g6_config.json` with the example block.
2. Run:
```powershell
python scripts/run_orchestrator_loop.py --config config/g6_config.json
```

## Troubleshooting
| Symptom | Likely Cause | Fix |
|--------|--------------|-----|
| No fancy panel | Env not set and config flag false | Set env or config `console.fancy_startup` |
| No panel at all | Banner disabled | Remove `G6_DISABLE_STARTUP_BANNER` or set `console.startup_banner=true` |
| Live panel missing | `G6_LIVE_PANEL` not set and config flag false | Set one of them |
| Analytics didn’t run | Both CLI flag and config flag false | Use `--analytics` or set `features.analytics_startup` |
| Flags ignored | JSON malformed or not loaded | Validate JSON syntax and path passed to `--config` |

## Implementation Notes
- The code evaluates ENV first, then config. For fancy panel and live panel the env variable being truthy is enough even if config says false.
- `--analytics` overrides both ENV and config (there is no env var for analytics to keep surface minimal).
- `console.startup_banner=false` suppresses all banner output even if `G6_FANCY_CONSOLE` is set.

## Future Extensions
Potential additions: `console.min_cycle_ms_warn`, `features.analytics_schedule` (cron), `console.live_panel_interval` (render every N cycles).

---
Last updated: 2025-09-16

## Adaptive Strike Depth Scaling (Passthrough Mode)

The adaptive scaling logic can operate in two modes:

1. Mutating (default): On scale changes the configured `strikes_itm/strikes_otm` values in `index_params` are rewritten to scaled counts.
2. Passthrough (`G6_ADAPTIVE_SCALE_PASSTHROUGH=1`): Baseline `index_params` remain untouched; a scale factor is stored in the runtime flags and applied at strike build time (`build_strikes(..., scale=<factor>)`). This preserves original config and makes scaling instantly reversible without drift.

Enabling:
```powershell
$env:G6_ADAPTIVE_STRIKE_SCALING=1; $env:G6_ADAPTIVE_SCALE_PASSTHROUGH=1
```

Related Environment Variables (existing):
- `G6_ADAPTIVE_STRIKE_BREACH_THRESHOLD` (default 3)
- `G6_ADAPTIVE_STRIKE_RESTORE_HEALTHY` (default 10)
- `G6_ADAPTIVE_STRIKE_REDUCTION` (default 0.8)
- `G6_ADAPTIVE_STRIKE_MIN` (minimum strikes per side)

Event Emission:
On every scale transition an `adaptive_scale_change` event is written to `logs/events.log` with context:
```jsonc
{ "event": "adaptive_scale_change", "context": { "old_scale": 1.0, "new_scale": 0.8, "breach_streak": 0, "healthy_streak": 0, "mode": "passthrough" } }
```

Migration Notes:
- Passthrough mode is backwards compatible; disabling it reverts to mutating behavior using the last stored baseline map.
- Tests assert that in passthrough mode `index_params` values do not change while strike lists shrink.

---
Last updated (adaptive section): 2025-09-26

## Panels Publisher Toggles
These control JSON panel publishing from the unified summary publisher. The legacy external bridge has been retired; all panel artifacts are produced in-process.

- G6_ENABLE_PANEL_PUBLISH=1
  - Enables the summary publisher to write panel JSONs (loop/provider/resources/etc.). If off, the function is a no-op.

- G6_PUBLISHER_EMIT_INDICES_STREAM=1
  - Opt-in to append to `indices_stream`. (Cadence now governed by unified loop; legacy bridge cadence logic removed.)

Example (PowerShell):
```powershell
$env:G6_ENABLE_PANEL_PUBLISH=1; $env:G6_PUBLISHER_EMIT_INDICES_STREAM=1; python scripts/run_orchestrator_loop.py --config config/g6_config.json
```

Notes:
- Duplicates are no longer a concern (single writer). Ensure downstream consumers tolerate potential future schema enrichment signaled via manifest `schema_version`.

## Async Collector Market-Hours Policy (Enforced)
The async parallel collector always enforces market-hours. Outside IST 09:15–15:30 on non-holiday weekdays, collection is skipped per index.

Behavior:
- Uses `src/utils/market_hours.py` `is_market_open(market_type="equity", session_type="regular")` which encodes 09:15–15:30 IST and 2025 holiday list.
- When closed, increments `collection_skipped{reason="market_closed"}` (if metrics are enabled) and returns without writes.

Notes:
- Tests and mocks that expect writes outside market hours should either inject a reference time into `is_market_open` (via helper wrappers) or run within the window. The project’s smoke tests are built to tolerate structure checks via placeholder creation where applicable.
