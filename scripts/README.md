# G6 Scripts

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

### Windows PowerShell tips

- If you started the simulator in background via the menu, a PID file is created next to your chosen status file (e.g., `data/.simulator.pid`). Use the menu Run → "Stop simulator (background)" to terminate it cleanly.
- If you need to kill a stuck simulator manually:

```
tasklist | findstr python
taskkill /PID <pid> /T /F
```
