# G6 Operator Manual

> Audience: Day-to-day platform operators / on-call engineers. Focus: running, monitoring, diagnosing, and safely restarting G6.

---
## 1. Quick Start
### 1.1 Prerequisites
- Python 3.11+ environment with dependencies from `requirements.txt`
- Network access to provider API (e.g., Kite)
- Valid auth token (managed via `src/tools/token_manager.py` or external process)
- Optional: InfluxDB reachable if persistence enabled
- Prometheus scraping endpoint network-accessible (usually `localhost`)

### 1.2 First Run
```
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60 --cycles 1
```
Check for:
- Startup banner (fancy or simple)
- Analytics block (if enabled)
- Collection summary lines

### 1.3 Continuous Run
```
python scripts/run_orchestrator_loop.py --config config/g6_config.json --interval 60
```
Leave running under a process manager (screen/tmux/service wrapper) or Windows Task Scheduler.

---
## 2. Configuration Touch Points
| Area | File / Env | Notes |
|------|------------|-------|
| Indices & expiries | `config/g6_config.json:index_params` | Enable/disable, strike depth |
| Greeks & IV | `config/g6_config.json:greeks` | Toggle analytics resource intensity |
| Fancy banner | `console.fancy_startup` / `G6_FANCY_CONSOLE` | Cosmetics + readiness overview |
| Live panel | `console.live_panel` / `G6_LIVE_PANEL` | Real-time cycle stats |
| ASCII enforcement | `console.force_ascii` / `G6_FORCE_ASCII` | Windows safety |
| Analytics startup | `features.analytics_startup` / `--analytics` | Early PCR insight |

Changes require process restart.

---
## 3. Runtime Monitoring
### 3.1 Prometheus Metrics
Scrape URL (example): `http://localhost:8000/metrics` (port defined inside metrics module; adjust accordingly). Confirm with browser or curl.

Critical Metrics to Watch:
| Purpose | Metric |
|---------|--------|
| Cycle freshness | `g6_last_success_cycle_unixtime` |
| Cycle errors | `g6_collection_errors_total` / `g6_index_failures_total` |
| Throughput | `g6_options_processed_per_minute` |
| IV health | `g6_iv_estimation_failure_total` |
| Memory state | `g6_memory_pressure_level` |
| Index success | `g6_index_success_rate_percent` |

### 3.2 Live Console Panel (If Enabled)
Shows per-cycle snapshot: success %, duration, throughput, memory. If missing metrics show NA for an index, it's a known limitation (pending wiring); rely on Prometheus dashboards.

### 3.3 Logs
Primary runtime log (if configured) or stdout. Tail example (PowerShell):
```
Get-Content g6_platform.log -Wait
```

Look for WARNING/ERROR entries referencing provider errors or write failures.

---
## 4. Health & Readiness
Health snapshot integrated in startup banner:
- Components (e.g., provider, metrics exporter)
- Checks (connectivity, token validity)

If a component is unhealthy:
1. Verify credentials / token freshness
2. Test connectivity with `scripts/quick_provider_check.py`
3. Restart process after remediation

---
## 5. Common Operational Tasks
| Task | Procedure |
|------|-----------|
| Refresh token | Run `python -m src.tools.token_manager` (adjust to provider specifics) |
| Add index | Edit `index_params` -> restart -> confirm metrics appear |
| Adjust strike depth | Modify `strikes_itm/strikes_otm` -> restart |
| Disable Greeks temporarily | Set `greeks.enabled=false` -> restart |
| Force ASCII | Set env `G6_FORCE_ASCII=1` or config value |
| Disable fancy banner | Env `G6_DISABLE_STARTUP_BANNER=1` or config flag |
| One-off analytics | `--analytics --run-once` |

---
## 6. Troubleshooting Matrix
| Symptom | Probable Cause | Action Steps |
|---------|----------------|-------------|
| No startup panel | Banner disabled or fancy preconditions failed | Check env `G6_DISABLE_STARTUP_BANNER`; look for info line `Startup banner mode:` |
| All indices show NA in live panel | Wiring gap (expected) | Use Prometheus dashboards for detail |
| IV failures spike | Vol model divergence / bad prices | Inspect logs for solver warnings; widen iv bounds or raise iteration cap |
| Collection stalls | Provider outage or auth expiration | Check token validity; attempt `quick_provider_check.py`; restart |
| Disk usage ballooning | No pruning strategy yet | Archive or rotate old CSVs manually; implement retention (roadmap) |
| High memory pressure level | Large strike depth or per-option metrics | Reduce configured strikes or disable Greeks temporarily |
| Missing overview snapshots | Market closed or index disabled | Confirm market hours; check `index_params.enable` |
| Influx write errors | Network / auth / bucket misconfig | Validate URL/org/bucket/token; test with influx CLI |

---
## 7. Safe Restart Procedure
1. Send gentle termination (Ctrl+C) or service stop
2. Wait for log line indicating graceful shutdown (cycle completion if mid-cycle)
3. Restart command
4. Confirm new `g6_last_success_cycle_unixtime` advancing

If hard-killed mid-cycle, partial CSV rows are still atomic (line-based); Influx conflicts are unlikely (timestamps differ by design).

---
## 8. Capacity & Scaling Considerations
| Lever | Impact |
|-------|--------|
| Reduce strikes_otm/itm | Fewer option rows → lower CPU & memory |
| Disable Greeks | Remove solver & Greeks overhead |
| Disable per-option metrics (future toggle) | Reduce Prom metrics cardinality |
| Increase interval_seconds | Fewer cycles → less sustained load |
| Add caching (planned) | Reduce redundant provider calls |

---
## 9. Security / Compliance Notes
- Do not commit tokens. Ensure `.gitignore` patterns cover credentials.
- Sanitize logs before sharing externally (may contain symbol pricing context).
- Limit network ingress to Prometheus endpoint where possible.

---
## 10. Backup & Retention (Interim)
Current: CSV accumulation with no automated purge.
Recommendation: Cron / scheduled task to move files older than N days to archive storage or compress by date.

Suggested Windows PowerShell compression example:
```
Get-ChildItem data -Recurse -Include *.csv -File | Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-14) } | `
ForEach-Object { Compress-Archive -Path $_.FullName -DestinationPath ($_.FullName + '.zip'); Remove-Item $_.FullName }
```
(Validate before removal.)

---
## 11. Upgrade Procedure
1. Pull new code / deploy artifact
2. Diff `requirements.txt`; install new deps in venv
3. Run `--run-once --analytics` to validate startup
4. Review CHANGELOG / `README.md` (Configuration & Feature Toggles) for new toggles
5. Deploy continuous run

Rollback: use previous git tag / commit; restart.

---
## 12. Roadmap Awareness for Operators
Expect future additions that might change observability patterns:
- Live panel per-index state (reduces NA fields)
- Data retention subsystem (automates pruning)
- Alerting rule pack (staleness, latency, pressure)

Prepare dashboards to adapt to metric name additions (prefix stable: `g6_`).

---
## 13. Pipeline Mode Wave 2 / 3 Enhancements (2025-10-08)

### 13.1 Parity Score Logging & Rolling Window
Enable via env `G6_PIPELINE_PARITY_LOG=1` and pass a legacy baseline snapshot into the pipeline orchestrator wrapper. Log record emitted:
- Logger: `src.collectors.pipeline`
- Message: `pipeline_parity_score`
- Extras: `score`, `components`, `missing`, plus when configured: `rolling_avg`, `rolling_count`, `rolling_window`, and `alerts_detail` (Wave 3).

Rolling parity average: set `G6_PARITY_ROLLING_WINDOW=<N>` (>1) to compute rolling average (gauge `g6_pipeline_parity_rolling_avg`). Target N=200 for promotion readiness.

Usage hint (pseudo-code):
```
legacy = collect_legacy_snapshot()
pipeline = run_pipeline(index_params, providers, csv_sink, influx_sink, legacy_baseline=legacy)
```

### 13.2 Extended Parity (Version 2)
Set `G6_PARITY_EXTENDED=1` to enable additional `strike_coverage` component and bump parity `version` to 2. Without flag remains version 1.

### 13.3 Alert Parity Weighting
Structured alerts block in snapshot is leveraged for category-aware parity. Optional weighting via `G6_PARITY_ALERT_WEIGHTS` format:
```
G6_PARITY_ALERT_WEIGHTS=low_strike_coverage:1.5,index_failure:3,low_field_coverage:1
```
If unset, all categories weight=1.0. Fallback to symmetric difference scoring when structured categories or weights absent. Gauge `g6_pipeline_alert_parity_diff` reports weighted normalized mismatch (0 perfect).

### 13.4 Phase Duration Metrics
Set `G6_PIPELINE_PHASE_METRICS=1` to emit histogram observations:
`pipeline_phase_duration_seconds{phase="<phase>"}`

### 13.5 Error Taxonomy Semantics
| Type | Typical Cause | Operator Action |
|------|---------------|-----------------|
| Recoverable (`PhaseRecoverableError`) | Expiry finalize anomaly, partial metadata | Monitor rate; if localized ignore or file issue |
| Fatal (`PhaseFatalError`) | Instrument universe failure, expiry map corruption | Investigate provider, consider rollback if sustained |

Trigger rollback drill if fatal rate >2% over 20 consecutive cycles or parity score <0.98 for 10 cycles.

### 13.6 Rollback Drill Script (Enhanced Wave 3)
`python scripts/rollback_drill.py` (dry-run) or add `--execute` to simulate live rollback path.

Steps performed (current skeleton):
1. Capture health snapshot placeholder
2. Disable pipeline flag (in-memory)
3. Legacy warm run placeholder

Wave 3 additions:
- Artifact persistence (`--artifact-dir`) capturing parity snapshot + anomaly summary.
- Metrics counter increment `g6_pipeline_rollback_drill_total`.
- Parity snapshot attempt pre-disable.

### 13.7 Benchmark Delta Automation
Use `python scripts/bench_delta.py` to run legacy vs pipeline micro-benchmark and enforce delta thresholds (p50/p95/mean). Environment `G6_BENCH_METRICS=1` enables metrics emission (counters/gauges TBD). Fails with non-zero exit if regression crosses threshold (for CI gating).

Runtime Continuous Benchmarking (Wave 4 W4-09/W4-10):
- Enable periodic in-process benchmark cycles: `G6_BENCH_CYCLE=1` (default interval 300s; override `G6_BENCH_CYCLE_INTERVAL_SECONDS`).
- Optional tuning: `G6_BENCH_CYCLE_INDICES`, `G6_BENCH_CYCLE_CYCLES`, `G6_BENCH_CYCLE_WARMUP`.
- Emit delta gauges: `g6_bench_delta_p50_pct`, `g6_bench_delta_p95_pct`, `g6_bench_delta_mean_pct` plus absolute p50/p95 gauges (legacy & pipeline).
- Configure alert threshold: `G6_BENCH_P95_ALERT_THRESHOLD` (percentage). When set, gauge `g6_bench_p95_regression_threshold_pct` emitted.

Alert: `BenchP95RegressionHigh`
Expression:
```
(g6_bench_delta_p95_pct > g6_bench_p95_regression_threshold_pct) and (g6_bench_p95_regression_threshold_pct >= 0)
```
Fires (warning) if sustained 5m. Action: Inspect recent deployments, provider latency, resource pressure (memory / CPU). If systemic, consider rollback or temporary strike depth reduction.

### 13.8 Taxonomy Counters
Operational counters exposed via metrics facade:
- `pipeline_expiry_recoverable_total`
- `pipeline_index_fatal_total`
Use `dump_metrics()` (test / debugging) or scrape Prometheus endpoint to confirm presence.

### 13.9 Rapid Investigation Playbook
```
export G6_PIPELINE_PARITY_LOG=1
export G6_PIPELINE_PHASE_METRICS=1
# run orchestrator for a few cycles
```
Review logs for `outcome=fatal` and parity score drift. If rollback required:
```
python scripts/rollback_drill.py --execute
```
Validate legacy cycle completes and alerts present.

---
## 14. Minimal Incident Playbook
| Incident | Quick Actions |
|----------|---------------|
| No cycles for >5 min | Check `g6_last_success_cycle_unixtime`; restart process; verify provider status page |
| Memory pressure >=3 | Reduce strike depth; disable Greeks; restart |
| IV failures 100% | Inspect pricing anomalies; temporarily set `estimate_iv=false`; restart |
| Disk full imminent | Stop process; archive/compress old CSV; resume |
| Metrics endpoint down | Check process alive; port conflict; restart or change port |

---
## 15. Contact & Handoff Notes
Maintain a short Handoff Log (outside repo) capturing:
- Last restart time & reason
- Outstanding anomalies (e.g., persistent IV failure on BANKNIFTY next_week)
- Temporary mitigations applied (e.g., Greeks disabled)

---
## 16. Quick Commands Cheat Sheet (PowerShell)
```
# Run continuously
python scripts/run_orchestrator_loop.py --config config\g6_config.json --interval 60

# Single diagnostics cycle with analytics
$env:G6_FANCY_CONSOLE=1; python scripts/run_orchestrator_loop.py --config config\g6_config.json --interval 60 --cycles 1 --analytics

# Tail log
Get-Content g6_platform.log -Wait

# Validate provider health
python scripts\quick_provider_check.py

# Token manager (example)
python -m src.tools.token_manager

# Show metrics snapshot
curl http://localhost:8000/metrics | Select-String g6_collection_cycles_total
```

---
End of manual.

---
## 16. Adaptive Alerts Badge (Severity / Decay / Resolution)
When `G6_ADAPTIVE_ALERT_SEVERITY=1`, the summary view (and potentially future UI surfaces) shows a compact adaptive alerts badge summarizing current elevated severities and lifecycle state.

Format Variants:
- Active elevations present: `Adaptive alerts: <total> [C:<critical> W:<warn>]` optionally followed by `R:<resolved>` if any recently decayed resolutions occurred the current cycle.
- Stabilized (no active warn/critical): `Adaptive alerts: <total> R:<resolved> (stable)` — severity counts are suppressed when both C and W are zero. `(stable)` indicates all tracked alert types have decayed back to `info`.

Fields:
| Element | Meaning |
|---------|---------|
| `<total>` | Count of alerts observed in the current aggregation window (unchanged from legacy) |
| `C:x` | Number of alerts currently classified critical (after streak / overrides) |
| `W:y` | Number of alerts currently classified warn |
| `R:n` | Number of alert types that transitioned from warn/critical back to info via decay this cycle (resolved events) |
| `(stable)` | Emitted only when there are zero active warn & critical severities after decay evaluation |

Resolution Semantics:
- A resolved event is emitted only when an alert type with prior active severity warn/critical passively downgrades to info due to inactivity (`G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES`), not when an alert fires with benign values.
- Multiple level decay can occur in one evaluation if the idle cycle gap spans several decay windows (e.g., critical→info directly) — still counted once for resolution.
- Disabled decay (`G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES=0`) means no resolutions appear (R omitted) and severities remain at last active level until a new alert causes reclassification.

Operator Guidance:
- Persistent critical counts: investigate upstream signal (e.g., high interpolation fraction or extreme drift). If critical persists without recovery, consider adjusting thresholds only after root cause analysis.
- High resolved counts with frequent re-escalation: may indicate threshold flapping; review raw metrics or widen decay window.
- `(stable)` plus rising total alerts typically means informational chatter without degradation; safe to deprioritize.

Key Environment Variables:
| Env | Purpose |
|-----|---------|
| `G6_ADAPTIVE_ALERT_SEVERITY` | Master enable for severity system |
| `G6_ADAPTIVE_ALERT_SEVERITY_RULES` | Override per-type warn/critical thresholds (JSON) |
| `G6_ADAPTIVE_ALERT_SEVERITY_MIN_STREAK` | Minimum consecutive trigger count before escalation above info |
| `G6_ADAPTIVE_ALERT_SEVERITY_DECAY_CYCLES` | Idle cycles before a decay downgrade (enables resolution lifecycle) |
| `G6_ADAPTIVE_ALERT_SEVERITY_FORCE` | Force overwrite of pre-existing severity fields on alerts |

Example Timeline (DECAY_CYCLES=3):
Cycle 10: interpolation_high fires at critical → Badge: `... [C:1 W:0]`
Cycle 11–13: no new interpolation_high → still within idle window → Badge unchanged
Cycle 14: decay triggers critical→warn → Badge: `... [C:0 W:1]`
Cycle 17: (another 3 idle cycles) warn→info decay emits resolved → Badge: `... R:1 (stable)`

See also: `docs/design/adaptive_alerts_severity.md` (Phase 2 specifics) and quick reference cheat sheet (if present).
On-Call Escalation (10-line guide): `docs/cheatsheets/oncall_adaptive_alerts_runbook.md`
