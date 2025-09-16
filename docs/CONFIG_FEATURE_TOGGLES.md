# G6 Feature & Console Toggles

This document explains how to enable analytics, the fancy startup panel, and the live per‑cycle panel.

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
$env:G6_FANCY_CONSOLE=1; $env:G6_LIVE_PANEL=1; python -m src.unified_main --config config/g6_config.json --analytics
```

Using only config (remove env vars):
1. Edit `config/g6_config.json` with the example block.
2. Run:
```powershell
python -m src.unified_main --config config/g6_config.json
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
