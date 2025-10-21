# G6 User Guide (2025-10-21)

This guide explains how to install, configure, run, and troubleshoot the G6 application.

## 1. Installation

- Install Python 3.11+ (Windows x64)
- Install Git and Visual Studio Code
- Clone the repo:
```
git clone https://github.com/ayushrajani07/G6_.git
cd G6_
```
- Create a virtual environment and install dependencies:
```
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 2. Configuration

- Optional environment variables:
  - G6_SSE_HTTP_PORT: default 9320
  - G6_SSE_API_TOKEN: set if you want to protect the SSE endpoint
  - HTTP_PROXY / HTTPS_PROXY: if behind a proxy
- Prometheus/Grafana (optional for dashboards):
  - Prometheus config: prometheus.yml (already included)
  - Grafana provisioning in grafana/; use provided tasks/scripts to start

## 3. Common tasks (VS Code Tasks)

- Initialize project menu:
  - Task: G6: Init Menu
- Start Observability Stack (Prometheus + Grafana):
  - Task: Observability: Start baseline
  - Or Grafana only: Grafana: Start (auto_stack)
- Clean Grafana state (optional):
  - Task: Observability: Clean Grafana state
- Start metrics exporter(s):
  - Task: Metrics: Start 9108 (runtime metrics)
  - Task: Metrics: Start overlay exporter (9109)
- Smoke demo:
  - Task: Smoke: Start Simulator
  - Task: Smoke: Summary (panels mode)
- Lint & tests:
  - Task: ruff: check (src & scripts)
  - Task: mypy: type-check (src)
  - Task: pytest - fast inner loop

## 4. Running the terminal summary

- Panels mode with periodic refresh:
```
.\.venv\Scripts\python.exe -m scripts.summary.app --refresh 0.5
```
- Plain one-shot summary:
```
python -m scripts.summary.app --no-rich --refresh 1
```

## 5. SSE/HTTP live dashboard

- Start Grafana (anonymous mode) and open analytics:
  - Task: G6: Restart + Open Analytics (Infinity)
- SSE harness (bench):
```
python scripts/summary/bench_sse.py --clients 5 --duration 15
```

## 6. Data & metrics

- Prometheus reads from the metrics server (see tasks for port 9108/9109 options)
- Key metrics and rules:
  - prometheus_rules.yml, prometheus_alerts.yml
  - See METRICS_CATALOG.md for meanings

## 7. Environment snapshot & restore

- Snapshot current machine environment:
```
scripts\tools\env_snapshot.ps1 -OutputDir env_snapshots_full
```
- Restore on a fresh machine:
```
scripts\tools\env_restore.ps1 -SnapshotDir <path-to-snapshot_YYYYMMDD_HHMMSS>
```

## 8. Troubleshooting

- Panel not loading / Grafana errors:
  - Run: Grafana: Persist env + restart or Grafana: Restart service
  - Check C:\GrafanaData and provisioning
- mypy/ruff failing in repo-wide checks:
  - Use incremental strict-typing (mypy.ini) and fix small batches; run "pytest - fast inner loop"
- Provider auth (Kite):
  - Run token manager:
```
.\.venv\Scripts\python.exe -m src.tools.token_manager
```

## 9. Tips

- Use tasks for most operations to avoid manual command churn
- Keep env snapshots outside the repo to avoid accidental commits (already .gitignored)
- Check RECOVERY_CHECKLIST.md for a fast restore plan

## 10. Command reference and flags (Windows PowerShell)

Below are direct commands to run common parts of the project. When using Python, prefer the venv interpreter:

```
.\.venv\Scripts\python.exe <module-or-script> [flags]
```

### 10.1 Summary UI (terminal)

- Panels mode (periodic refresh):
```
.\.venv\Scripts\python.exe -m scripts.summary.app --refresh 0.5
```
  - Flags:
    - --refresh <seconds>: UI refresh interval (float)
    - --no-rich: render plain text (no Rich formatting)
  - Environment:
    - G6_PANELS_DIR: when set (e.g., data/panels), switches app to panels mode

- Plain one-shot summary:
```
.\.venv\Scripts\python.exe -m scripts.summary.app --no-rich --refresh 1
```

### 10.2 Smoke simulator and summary

- Start simulator (status + metrics server + indices + open market):
```
.\.venv\Scripts\python.exe scripts/dev_tools.py simulate-status \
  --status-file data/runtime_status.json \
  --start-metrics-server \
  --indices NIFTY BANKNIFTY FINNIFTY SENSEX \
  --interval 60 \
  --refresh 1.0 \
  --open-market \
  --with-analytics
```
  - Flags:
    - --status-file <path>: runtime status JSON to read/write
    - --start-metrics-server: also start a metrics HTTP server
    - --indices <list...>: space-separated index names
    - --interval <sec>: update interval
    - --refresh <sec>: simulator internal refresh
    - --open-market: simulate open market conditions
    - --with-analytics: include analytics fields

- Summary (panels mode) reading simulator status:
```
$env:G6_PANELS_DIR = "data/panels"
.\.venv\Scripts\python.exe -m scripts.summary.app --refresh 0.5
```

### 10.3 SSE/HTTP harness (load/latency)

```
.\.venv\Scripts\python.exe scripts/summary/bench_sse.py \
  -H 127.0.0.1 -p 9320 --path /summary/events \
  --clients 10 --duration 15 \
  --token $env:G6_SSE_API_TOKEN --json
```
  - Flags:
    - -H/--host <ip/host>: SSE host (default 127.0.0.1)
    - -p/--port <int>: SSE port (default 9320 or env G6_SSE_HTTP_PORT)
    - --path <string>: SSE path (default /summary/events)
    - -c/--clients <int>: concurrent connections (default 5)
    - -d/--duration <sec>: wall-clock duration (default 15)
    - -t/--token <string>: X-API-Token header value
    - --json: emit JSON-only output

### 10.4 Metrics exporters

- Runtime metrics server (default 9108):
```
.\.venv\Scripts\python.exe scripts/start_metrics_server.py --host 127.0.0.1 --port 9108
```
  - Flags:
    - --host <ip>
    - --port <int>

- Overlay exporter (default 9109):
```
.\.venv\Scripts\python.exe scripts/overlay_exporter.py \
  --host 127.0.0.1 --port 9109 \
  --base-dir data/g6_data \
  --weekday-root data/weekday_master \
  --status-file data/runtime_status.json
```
  - Flags:
    - --host/--port: listen address/port
    - --base-dir <path>: base data directory
    - --weekday-root <path>: generated weekday overlays root
    - --status-file <path>: runtime status JSON

### 10.5 Overlays generation

- Generate weekday master (today):
```
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts/weekday_overlay.py --all --base-dir data/g6_data --output-dir data/weekday_master
```

- Generate weekday master (specific date):
```
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe scripts/weekday_overlay.py --all --date 2025-10-21 --base-dir data/g6_data --output-dir data/weekday_master
```
  - Flags:
    - --all: process all configured symbols/indices
    - --date YYYY-MM-DD: override processing date (default: today)
    - --base-dir <path>: input base directory
    - --output-dir <path>: output directory

### 10.6 Observability stack & Grafana helpers

- Start baseline stack (Prometheus + Grafana, anonymous):
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/obs_start.ps1 -GrafanaAllowAnonymous -OpenBrowser
```
  - Flags (subset):
    - -PrometheusExe <path>: custom Prometheus executable
    - -GrafanaAllowAnonymous: allow anonymous access
    - -GrafanaAnonymousEditor: grant editor role to anonymous users
    - -OpenBrowser: open Grafana automatically

- Start/stop individual services (auto_stack):
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/auto_stack.ps1 -StartPrometheus:$true -StartInflux:$false -StartGrafana:$true -OpenBrowser
```
  - Switches:
    - -StartPrometheus:$true|$false
    - -StartInflux:$true|$false
    - -StartGrafana:$true|$false
    - -GrafanaAllowAnonymous (switch)
    - -OpenBrowser (switch)

- Restart stack and open Analytics (Infinity):
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/restart_stack_and_open_analytics.ps1 -GrafanaPort 3002 -DisablePassword -Clean -OpenBrowser
```
  - Flags:
    - -GrafanaPort <int>: override Grafana port
    - -DisablePassword: enable anonymous admin
    - -Clean: stop running processes before start
    - -OpenBrowser: open the dashboard URL

- Grafana env setup (session or persist) and restart:
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/grafana_env_setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -Command "& 'scripts/grafana_env_setup.ps1' -Persist; & 'scripts/grafana_restart.ps1'"
```
  - -Persist: write env to system/user so Grafana service picks it up

### 10.7 Config utilities

- Config Guard:
```
.\.venv\Scripts\python.exe scripts/config_guard.py check
.\.venv\Scripts\python.exe scripts/config_guard.py update
```

- Patch Grafana dashboards to Prometheus data source:
```
.\.venv\Scripts\python.exe scripts/tools/grafana_ds_patch.py "${PWD}"
```

### 10.8 Tests and quality

- Fast inner loop tests:
```
.\.venv\Scripts\python.exe scripts/pytest_run.py fast-inner
```
- Parallel subset tests:
```
.\.venv\Scripts\python.exe scripts/pytest_run.py parallel-subset
```
- Serial-only tests:
```
.\.venv\Scripts\python.exe scripts/pytest_run.py serial
```
- Lint (ruff) check/fix:
```
.\.venv\Scripts\python.exe -m ruff check src scripts
.\.venv\Scripts\python.exe -m ruff check --fix src scripts
```
- Type-check (mypy):
```
.\.venv\Scripts\python.exe -m mypy src
```

### 10.9 Auth and tokens

- Kite token manager (login/refresh):
```
.\.venv\Scripts\python.exe -m src.tools.token_manager
```

### 10.10 Mock/Prometheus-only stacks

- Mock stack (no Prometheus):
```
powershell -NoProfile -ExecutionPolicy Bypass -File .\auto_stack_mock.ps1 -NoProm
```
- Mock stack (+ Prometheus with custom exe/config):
```
powershell -NoProfile -ExecutionPolicy Bypass -File .\auto_stack_mock.ps1 -PrometheusExe "C:\\path\\prometheus.exe" -PromConfig "C:\\path\\prometheus.yml"
```

## 11. Entry points (quick launcher)

These are the primary entry points across the project. Use `--help` where available to discover additional flags.

### 11.1 Core runtime and summary

- Unified loop (summary runtime; if enabled in your setup):
```
.\.venv\Scripts\python.exe scripts\summary\unified_loop.py --help
```

- SSE/HTTP summary endpoint:
```
.\.venv\Scripts\python.exe scripts\summary\unified_http.py --help
```

- Terminal Summary UI (Rich panels):
```
.\.venv\Scripts\python.exe -m scripts.summary.app --refresh 0.5
```

### 11.2 Summary tools and maintenance

- Snapshot builder (generate summary snapshot artifacts):
```
.\.venv\Scripts\python.exe scripts\summary\snapshot_builder.py --help
```

- Status re-sync utilities:
```
.\.venv\Scripts\python.exe scripts\summary\resync.py --help
```

- Schema helpers/validation (where applicable):
```
.\.venv\Scripts\python.exe scripts\summary\schema.py --help
```

### 11.3 Benchmarks / harnesses

- SSE load/throughput harness:
```
.\.venv\Scripts\python.exe scripts\summary\bench_sse.py --help
```

- Cycle benchmark harness:
```
.\.venv\Scripts\python.exe scripts\summary\bench_cycle.py --help
```

### 11.4 Metrics and exporters

- Runtime metrics server:
```
.\.venv\Scripts\python.exe scripts\start_metrics_server.py --host 127.0.0.1 --port 9108
```

- Overlay metrics exporter:
```
.\.venv\Scripts\python.exe scripts\overlay_exporter.py --help
```

### 11.5 Overlays and data tooling

- Weekday overlays generator (today or specific date):
```
.\.venv\Scripts\python.exe scripts\weekday_overlay.py --help
```

- Overlay replay:
```
.\.venv\Scripts\python.exe scripts\overlay_replay.py --help
```

### 11.6 Observability stack (PowerShell)

- Start baseline stack (Prom + Grafana):
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\obs_start.ps1 -OpenBrowser
```

- Start specific services (auto_stack):
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\auto_stack.ps1 -StartPrometheus:$true -StartInflux:$false -StartGrafana:$true -OpenBrowser
```

- Restart Grafana and open dashboards:
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restart_stack_and_open_analytics.ps1 -OpenBrowser
```

- Grafana environment setup and restart:
```
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\grafana_env_setup.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\grafana_restart.ps1
```

### 11.7 Configuration and maintenance

- Config Guard (check/update):
```
.\.venv\Scripts\python.exe scripts\config_guard.py check
.\.venv\Scripts\python.exe scripts\config_guard.py update
```

- Grafana dashboards DS patch (Prometheus):
```
.\.venv\Scripts\python.exe scripts\tools\grafana_ds_patch.py "${PWD}"
```

### 11.8 Auth and tokens

- Kite login/refresh:
```
.\.venv\Scripts\python.exe -m src.tools.token_manager
```

### 11.9 Testing and quality

- Pytest router:
```
.\.venv\Scripts\python.exe scripts\pytest_run.py --help
```

- Lint / Typecheck:
```
.\.venv\Scripts\python.exe -m ruff check src scripts
.\.venv\Scripts\python.exe -m mypy src
```
