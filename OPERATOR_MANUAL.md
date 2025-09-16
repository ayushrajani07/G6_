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
python -m src.unified_main --run-once --config config/g6_config.json
```
Check for:
- Startup banner (fancy or simple)
- Analytics block (if enabled)
- Collection summary lines

### 1.3 Continuous Run
```
python -m src.unified_main --config config/g6_config.json
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
4. Review CHANGELOG / `README_COMPREHENSIVE.md` sections for new toggles
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
## 13. Minimal Incident Playbook
| Incident | Quick Actions |
|----------|---------------|
| No cycles for >5 min | Check `g6_last_success_cycle_unixtime`; restart process; verify provider status page |
| Memory pressure >=3 | Reduce strike depth; disable Greeks; restart |
| IV failures 100% | Inspect pricing anomalies; temporarily set `estimate_iv=false`; restart |
| Disk full imminent | Stop process; archive/compress old CSV; resume |
| Metrics endpoint down | Check process alive; port conflict; restart or change port |

---
## 14. Contact & Handoff Notes
Maintain a short Handoff Log (outside repo) capturing:
- Last restart time & reason
- Outstanding anomalies (e.g., persistent IV failure on BANKNIFTY next_week)
- Temporary mitigations applied (e.g., Greeks disabled)

---
## 15. Quick Commands Cheat Sheet (PowerShell)
```
# Run continuously
python -m src.unified_main --config config\g6_config.json

# Single diagnostics cycle with analytics
$env:G6_FANCY_CONSOLE=1; python -m src.unified_main --config config\g6_config.json --analytics --run-once

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
