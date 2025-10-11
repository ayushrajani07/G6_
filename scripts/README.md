# G6 Scripts

## Observability Stack (Windows Auto-Resolve)

- Canonical: `scripts/auto_stack.ps1`
- Behavior: starts Prometheus, InfluxDB, and Grafana concurrently; waits 10s; checks health; iterates to next free port for any failed service with another 10s wait, until healthy or ports exhausted.
- Integration: invoked automatically by `auto_resolve_stack.py` at launcher start on Windows.
- Replaces: legacy `start_all.ps1`, `start_all_enhanced.ps1`, `start_grafana.ps1` (removed on 2025-10-11).

Run directly (optional):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\auto_stack.ps1
```

## init_menu.py (Interactive setup)

A simple, dependency-free menu to configure and launch common tools with organized submenus:

- Configure: grouped submenus for Status & Timing, Indices, Summary Display, and Simulator Flags
- Run: start/stop the Status Simulator (foreground or background) and launch the Terminal Summarizer
- Presets: save and load presets to `config/init_preset.json`
- About/Exit

### Run

```
python scripts/init_menu.py
```

### Configure → Status & Timing

- Status file path: where the simulator writes and the summarizer reads (default: `data/runtime_status.json`)
- Cycle interval: seconds between simulator cycles
- Refresh: UI refresh for summarizer and step delay inside simulator

### Configure → Indices

- Indices: comma-separated symbol list (default: NIFTY,BANKNIFTY,FINNIFTY,SENSEX)

### Configure → Summary Display

- Compact: reduce panel sizes and row limits
- Low Contrast: neutral border colors for certain terminal themes
- Rich vs Plain: use Rich if installed, or a plain-text fallback
- Metrics URL: optional link shown in the summary UI

### Configure → Simulator Flags

- Open Market: mark market state as OPEN/CLOSED in the simulator
- Analytics: include a small analytics payload in the simulator output

### Run submenu

- Start simulator (foreground): runs in the current terminal until Ctrl+C
- Start simulator (background): spawns a background process and stores its PID alongside the status file as `.simulator.pid`
- Stop simulator (background): reads PID from `.simulator.pid` and terminates the process
- Start summarizer: opens the overview UI (Rich if available; plain otherwise)
- Start both: starts the simulator in background and then opens the summarizer in one step

### Useful Commands (optional)

- Start the simulator directly:
  ```
  python scripts/dev_tools.py simulate-status --status-file data/runtime_status.json --interval 60 --refresh 1.0 --open-market --with-analytics
  ```
- Start the summarizer directly:
  ```
  python scripts/dev_tools.py summary --status-file data/runtime_status.json --refresh 1.0
  ```

### VS Code Task

Use the task panel to quickly launch the menu:
- Run Task → `G6: Init Menu`

#### One-click Panels Demo (VS Code)

You can run the full Simulator → Panels Bridge → Summary chain via VS Code tasks:

- Run Task → `Smoke: Summary (panels mode)`
  - Starts the simulator in background
  - Starts the panels bridge in background (writes `data/panels/*.json`)
  - Launches the summary UI with panels mode enabled

Tip: If you prefer to run steps individually, use:
- `Smoke: Start Simulator`
- `Smoke: Start Panels Bridge`
- `Smoke: Summary (panels mode)`

### Windows PowerShell tips

- If you started the simulator in background via the menu, a PID file is created next to your chosen status file (e.g., `data/.simulator.pid`). Use the menu Run → "Stop simulator (background)" to terminate it cleanly.
- If you need to kill a stuck simulator manually:

```
tasklist | findstr python
taskkill /PID <pid> /T /F
```

## Windows Quick Start: Simulator → Unified Summary (Panels In-Process)

Fast path to see Rich dashboard with IST timestamps and DQ:

1) Generate a demo status with seeded DQ (one-shot)

```powershell
python scripts/status_simulator.py --status-file data/runtime_status_demo.json --indices NIFTY,BANKNIFTY,FINNIFTY,SENSEX --interval 60 --refresh 0.1 --open-market --with-analytics --cycles 1
```

2) Launch the summary (panels auto-write/read via PanelsWriter; no separate bridge):

```powershell
python -m scripts.summary.app --refresh 0.5 --status-file data/runtime_status_demo.json
```

Continuous simulation + summary in two terminals:

```powershell
# Terminal 1: simulator
python scripts/dev_tools.py simulate-status --status-file data/runtime_status.json --indices NIFTY BANKNIFTY FINNIFTY SENSEX --interval 60 --refresh 1.0 --open-market --with-analytics

# Terminal 2: summary (panels mode auto-detected or force via env)
python -m scripts.summary.app --refresh 0.5 --status-file data/runtime_status.json
```

Notes:
- Frontend displays use IST HH:MM:SS; backend JSON remains ISO.
- Legacy bridge (`status_to_panels.py`) has been removed from the workflow; all panel JSON produced in-process.

## Maintenance Utilities

For quick developer hygiene actions (purge caches, verify summary app syntax, run targeted tests) use `maintenance.py`:

```powershell
# Purge __pycache__ + *.pyc and import-check summary app
python scripts/maintenance.py --purge-cache --check-summary

# Run a single test file after purge
python scripts/maintenance.py --purge-cache --run tests/test_cadence.py

# Full cycle: purge + check + full test suite (quiet)
python scripts/maintenance.py --all
```

Flags:
| Flag | Purpose |
|------|---------|
| `--purge-cache` | Remove all bytecode caches to avoid stale IndentationErrors |
| `--check-summary` | Import `scripts.summary.app` and report success |
| `--run <path>` | Run a specific pytest path for fast feedback |
| `--full` | Run full pytest suite (`-q`) |
| `--all` | Shortcut: purge + check-summary + full |
| `--dry-run` | Show actions without executing destructive steps |

Exit code is non-zero on first failure (import or pytest).
