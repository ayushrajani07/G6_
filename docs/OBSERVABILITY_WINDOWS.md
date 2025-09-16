# G6 Observability (Windows Native)

This guide helps you run the full observability stack (Prometheus + Grafana + G6 collectors) without Docker on Windows.

## Components
- **G6 Collector**: Exposes metrics on configured port (default 9108).
- **Prometheus**: Scrapes metrics targets (g6, itself, etc.).
- **Grafana**: Visualizes time‑series data with pre-provisioned dashboard.

## Folder/Path Conventions
Environment overrides (already appended to `.env`):
```
GF_PATHS_DATA=./grafana-data
GF_PATHS_LOGS=./grafana-data/logs
GF_PATHS_PLUGINS=./grafana-data/plugins
GF_PATHS_PROVISIONING=./grafana/provisioning
```
You can change these before starting Grafana; directories are created automatically on first run.

## Prometheus Setup
1. Download Windows build from: https://prometheus.io/download/
2. Extract to: `C:\Prometheus` (or adjust `-PrometheusDir` parameter).
3. Place the repo `prometheus.yml` in a readable path (default used by scripts).
4. Confirm the scrape target for g6 points to the correct host/port (default `localhost:9108`).

Validate: Run manually once:
```
C:\Prometheus\prometheus.exe --config.file=prometheus.yml
```
Open http://localhost:9090/targets – g6 target should be UP.

## Grafana Startup
Script: `scripts/start_grafana.ps1`
Key switches:
- `-Foreground`: Run attached (CTRL+C stops).
- `-AltPort`: Use port 3030 instead of 3000.

Examples:
```
powershell -ExecutionPolicy Bypass -File .\scripts\start_grafana.ps1 -Foreground
powershell -ExecutionPolicy Bypass -File .\scripts\start_grafana.ps1 -AltPort
```
Dashboard auto-provisioned: `G6 Observability` (if provisioning paths correct).

## All-In-One Launcher
`scripts/start_all.ps1` starts:
1. Prometheus (if `prometheus.exe` found).
2. Grafana (detached PowerShell window minimized).
3. G6 collector (`python -m src.main`).

Parameters:
- `-PrometheusDir` path to Prometheus folder.
- `-PromConfig` path to Prometheus yaml.
- `-GrafanaHome` root Grafana install dir.
- `-PythonExe` venv python path.
- `-CollectorModule` alternate module (e.g. `src.main_advanced`).
- `-ForegroundGrafana` pass through to run Grafana inline.
- `-AltGrafanaPort` use 3030 port.

Example:
```
powershell -ExecutionPolicy Bypass -File .\scripts\start_all.ps1 -ForegroundGrafana -CollectorModule src.main_advanced
```

## Stopping Services
- Grafana: `scripts/stop_grafana.ps1` (graceful then force).
- Prometheus: Close its console window or kill process.
- Collector: `Stop-Process` by its PID (shown in Task Manager as python). Consider adding a PID file if needed (future enhancement).

## Installing Grafana as Windows Service
Preferred: NSSM wrapper (graceful stop & restart handling).
1. Download NSSM: https://nssm.cc/download
2. Place at `C:\nssm\win64\nssm.exe` (or adjust parameter).
3. Run:
```
powershell -ExecutionPolicy Bypass -File .\scripts\install_grafana_service.ps1 -ServiceName Grafana -GrafanaHome "C:\Program Files\GrafanaLabs\grafana\grafana-12.1.1"
```
Then:
```
Start-Service Grafana
Get-Service Grafana
```

## Verifying Metrics Flow
1. Collector running (check its console or add temporary log prints).
2. Prometheus Targets page (g6 target UP).
3. Grafana Explore: query `g6_api_response_latency_ms_bucket` or `g6_api_success_rate`.
4. Dashboard panels populate (some need data over several cycles for EMA smoothing).

## Useful Prometheus Queries
- P95 API latency (ms):
  `histogram_quantile(0.95, sum by (le) (rate(g6_api_response_latency_ms_bucket[5m])))`
- Success rate (%):
  `avg_over_time(g6_api_success_rate[5m])`
- Cycle throughput (per min):
  `rate(g6_collection_cycles_total[5m]) * 60`

## Troubleshooting
| Symptom | Check | Fix |
|---------|-------|-----|
| Grafana 404 / port busy | `netstat -ano | findstr 3000` | Use `-AltPort` or stop conflicting process |
| Dashboard empty | Datasource not provisioned | Confirm paths & `GF_PATHS_PROVISIONING` env |
| Prometheus g6 DOWN | Metrics endpoint path | Ensure collector exposes `/metrics` & port matches config |
| Latency panels flat | Insufficient traffic | Generate API calls or extend time range |
| Resource metrics zero | psutil missing | `pip install psutil` and restart collector |

## Memory Control & NSSM Considerations
NSSM itself is lightweight; memory spikes typically originate from the wrapped application (Grafana plugins, Python collector, InfluxDB). Windows does not provide cgroup-like caps natively; rely instead on:

1. Application Tuning:
   - Grafana: Disable unused plugins, reduce dashboard auto-refresh intervals.
   - InfluxDB: Use retention policies & shard duration alignment.
   - Python Collector: Reduce strike depth defaults or batch sizes if chronic pressure.
2. Adaptive Degradation (implemented): Automatically scales depth, suppresses Greeks/metrics under pressure.
3. Alerting: Prometheus + Alertmanager rules now replace the old watchdog script (removed) for early warning.
4. Optional Advanced: Windows Job Objects or containers if hard isolation later.

Removed: The previous PowerShell memory watchdog script; superseded by in-process adaptive logic and alerting.

NSSM does not implement hard memory limits. For strict caps consider a wrapper using Job Objects or moving to containerization.

## Adaptive Degradation (Graceful Performance Trade-offs)
Instead of killing the collector under memory pressure, the platform now supports tiered degradation:

| Tier | Level | Trigger (EMA of RSS / Physical) | Actions |
|------|-------|----------------------------------|---------|
| normal | 0 | <70% | None |
| elevated | 1 | ≥70% | shrink_cache (placeholder) |
| high | 2 | ≥80% | shrink_cache, reduce_depth (halve strikes), skip_greeks, slow_cycles (sleep 250ms) |
| critical | 3 | ≥90% | All above + drop_per_option_metrics (skip high-cardinality option gauges) |

Metrics:
- `g6_memory_pressure_level` exposes current level.
- `g6_memory_pressure_actions_total{action,tier}` counts action executions.

Effects:
- `reduce_depth`: halves `strikes_itm` / `strikes_otm` but never below 2.
- `skip_greeks`: disables both Greek computation and IV estimation to reduce CPU & temporary allocations.
- `slow_cycles`: adds small sleeps to allow GC scheduling and reduce churn.
- `drop_per_option_metrics`: suppresses per-option metrics emission (largest label cardinality reduction) to lower memory in Prometheus client and ingestion.

Reset Behavior:
Actions remain active until process restart (idempotent) or pressure drops below previous thresholds; current implementation does not yet re-enable features automatically—future enhancement could add hysteresis.

Tuning:
- Adjust thresholds in `src/utils/memory_pressure.py` if your host memory differs significantly.
- For deterministic tests, set env var with smaller physical memory override (future: add CLI flag to pass total_physical_mb).

Observability:
Create Grafana panel for: `g6_memory_pressure_level` (stat) and `increase(g6_memory_pressure_actions_total[1h])` (table grouped by action).

Roadmap Enhancements (optional):
- Hysteresis to re-enable Greeks once back under 60%.
- Cache shrink integration (real cache references).
- Dynamic strike depth scaling proportional to pressure instead of halving once.
- Per-option metrics sampling (e.g., only ATM ± N strikes when critical).

## Adaptive Degradation Advanced (Implemented Enhancements)
The optional enhancements extend the initial system with:

### New Metrics
| Metric | Description |
|--------|-------------|
| g6_memory_pressure_seconds_in_level | Seconds elapsed in current pressure level |
| g6_memory_pressure_downgrade_pending | 1 when downgrade hysteresis condition waiting to complete |
| g6_memory_depth_scale | Current scaling factor applied to strike depth (0.2–1.0) |
| g6_memory_per_option_metrics_enabled | Whether full per-option metrics are currently emitted |
| g6_memory_greeks_enabled | Whether Greeks / IV computation currently active |

### Progressive Scaling
Strike depth now scales instead of abrupt halving:
Level mapping (base): Normal=1.0, Elevated=0.85, High=0.6, Critical=0.4 (further 0.8 multiplier if EMA >95%).

### Sampling / Suppression
Critical pressure suppresses per-option metrics entirely. You can adjust ATM window for metrics via `G6_OPTION_METRIC_ATM_WINDOW` (future extension to sample subset).

### Hysteresis & Rollback
Downgrades require sustained recovery (`G6_MEMORY_PRESSURE_RECOVERY_SECONDS`, default 60s). After downgrade:
- Greeks automatically re-enable after `G6_MEMORY_ROLLBACK_COOLDOWN` (default 120s).
- Per-option metrics re-enable after 2x that cooldown.

### Environment Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| G6_MEMORY_PRESSURE_TIERS | (unset) | JSON array overriding tiers (name,level,threshold,actions) |
| G6_MEMORY_PRESSURE_RECOVERY_SECONDS | 60 | Seconds below lower threshold before downgrade allowed |
| G6_MEMORY_ROLLBACK_COOLDOWN | 120 | Cooldown before feature re-enable after downgrade |
| G6_OPTION_METRIC_ATM_WINDOW | 3 | Base ATM ± window for future partial sampling |

Example override (PowerShell):
```
$env:G6_MEMORY_PRESSURE_TIERS='[{"name":"normal","level":0,"threshold":0,"actions":[]},{"name":"elevated","level":1,"threshold":0.65,"actions":["shrink_cache"]},{"name":"high","level":2,"threshold":0.78,"actions":["shrink_cache","reduce_depth","skip_greeks","slow_cycles"]},{"name":"critical","level":3,"threshold":0.9,"actions":["shrink_cache","reduce_depth","skip_greeks","slow_cycles","drop_per_option_metrics"]}]'
```

### Grafana Panels Added
- Depth Scale (stat)
- Greeks Enabled (stat)
- Per-Option Metrics Enabled (stat)
- Seconds in Level / Downgrade Pending (time series)
- Existing Memory Pressure Level & Actions remain.

### Operational Tuning Tips
- Watch `g6_memory_pressure_depth_scale` near 0.6/0.4 thresholds to anticipate feature suppression.
- Correlate `g6_memory_pressure_actions_total` spikes with throughput drops to refine tier thresholds.
- If Greeks are frequently toggled, raise High tier threshold or increase rollback cooldown.

### Future Extensions (Not Implemented Yet)
- Partial per-option sampling (ATM window filtering for metrics while still processing full dataset internally).
- Recording rule for pressure transitions as annotation source.
- Automatic strike depth ramp-up (gradual vs instant) post-recovery.

## Recording Rules & Annotations (New)
Prometheus recording rules have been added in `prometheus_rules.yml` and loaded via the `rule_files` section in `prometheus.yml`.

### Key Recorded Series
| Rule | Purpose |
|------|---------|
| g6_memory_pressure_transition | Positive value when a level upgrade occurred (difference vs 30s ago) |
| g6_memory_pressure_downgrade | Positive value when a level downgrade occurred |
| g6_memory_pressure_actions_5m | Aggregated mitigation actions executed over last 5 minutes |
| g6_memory_depth_scale_current | Convenience copy of current depth scale for alerting/panel math |
| g6_memory_greeks_enabled_flag | Flag copy tagged with job label |
| g6_memory_per_option_metrics_enabled_flag | Flag copy tagged with job label |

### Using in Grafana Annotations
1. Dashboard Settings -> Annotations -> New.
2. Query example (Upgrades):
```
g6_memory_pressure_transition > 0
```
Set Text: `Memory pressure upgrade`.
3. For downgrades:
```
g6_memory_pressure_downgrade > 0
```
Text: `Memory pressure downgrade`.

Optionally display level after transition:
```
g6_memory_pressure_level
```
and reference it in annotation text using template variables if using Grafana transformations.

### Alert / Future Automation Ideas
- Trigger alert if `g6_memory_depth_scale_current < 0.5` for > 10m.
- Alert when more than 3 upgrades in 30m:
```
sum(increase(g6_memory_pressure_transition[30m])) > 3
```
- Alert if Greeks disabled continuously for longer than rollback cooldown * 2 (indicates chronic pressure):
```
(time() - max_over_time(g6_memory_greeks_enabled[2h])*0) > 2400
```
Adjust windows to your environment.

### Operational Notes
The transition rules use a 30s lookback offset – ensure scrape/evaluation interval (15s) remains <= half that. If you change Prometheus `evaluation_interval`, adjust the offset consistently.

---

## Security Notes
- By default everything binds to localhost. Do not expose without auth / reverse proxy.
- For remote dashboards use SSH tunnel instead of opening ports publicly.

## Next Enhancements (Optional)
- Add recording rules (P95 latency, success SLO windows).
- Add alertmanager & basic alerts (latency, success rate, scrape failures).
- PID files & unified stop script.
- Service wrappers for Prometheus & Collector.

---
Maintained: Observability bootstrap v1.
