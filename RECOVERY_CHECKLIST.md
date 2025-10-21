# Rapid Recovery Checklist (Windows, PowerShell)

Use this checklist to capture your current setup and quickly restore it after formatting your PC.

## Before Formatting (Snapshot)

1) Optional: Commit/push latest repo changes to remote.
2) In this repo root, run the snapshot script:

```
# In PowerShell
scripts\tools\env_snapshot.ps1 -OutputDir env_snapshots
```

This creates a timestamped folder under `env_snapshots/` with:
- system_info.json (OS info)
- env_vars.json (filtered env vars: G6_*, Grafana/Prom/Influx, Python, proxies)
- requirements.freeze.txt and python_version.txt (if Python found)
- copies of key project configs (ruff, mypy, pytest, prometheus, alert rules)
- lightweight Grafana config/provisioning snapshot (if C:\GrafanaData exists)

Optionally, back up `env_snapshots/` and `C:\GrafanaData` externally.

## After Formatting (Restore)

1) Install essentials:
- Install Python (3.11+ recommended)
- Install Git and VS Code

2) Clone the repo:
```
git clone <your-remote-url>
cd g6_reorganized
```

3) Restore from snapshot:
```
# Path to the snapshot directory you created earlier
scripts\tools\env_restore.ps1 -SnapshotDir <path-to-snapshot_YYYYMMDD_HHMMSS>
```
This will:
- Recreate a fresh `.venv` and install deps (using requirements.freeze.txt if present, otherwise requirements.txt)
- Restore Grafana configs to `C:\GrafanaData` (non-destructive)
- Restore `prometheus.yml` to the repo root if it was snapshotted

4) Open in VS Code and run tasks:
- Use Task: `G6: Init Menu` once
- For Grafana:
  - `G6: Restart Grafana (passwordless)` or `Grafana: Start (auto_stack)`
- For quick smoke:
  - `Smoke: Start Simulator` then `Smoke: Summary (panels mode)`
- For lint/tests:
  - `ruff: check (src & scripts)`
  - `pytest - fast inner loop`

## Notes
- Env vars: Check `env_vars.json` for any values you want to reapply system-wide (e.g., proxies, G6_*). Prefer setting them per-session with `scripts/grafana_env_setup.ps1` or system Environment Variables UI.
- Grafana: If you rely on dashboards/plugins, consider keeping a full backup of `C:\GrafanaData` separately.
- Prometheus: The repo includes `prometheus.yml` and rules; the snapshot script copies the current version for convenience.
- Security: Don’t commit snapshots containing secrets. Store them securely.

## Troubleshooting
- If Python not found during snapshot, the script falls back gracefully. After restore, the script uses your installed Python.
- If ruff/mypy not found after restore, they’ll be installed via `requirements.txt` or the freeze file.
- If Grafana service conflicts, use tasks `Grafana: Restart service` or `Grafana: Persist env + restart`.
