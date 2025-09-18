from __future__ import annotations
import os
import sys
import subprocess
from typing import List, Optional, Dict


def _python_exe() -> str:
    # Prefer current venv python
    try:
        return sys.executable or "python"
    except Exception:
        return "python"


def _run(cmd: List[str], env: Optional[Dict[str, str]] = None) -> int:
    try:
        # On Windows PowerShell, use direct subprocess without shell to preserve Ctrl+C behavior
        proc = subprocess.Popen(cmd, env=env or os.environ.copy())
        proc.wait()
        return proc.returncode or 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Failed to start: {' '.join(cmd)} -> {e}")
        return 2


def menu_loop() -> int:
    py = _python_exe()
    default_choice = "1"
    while True:
        os.system("")  # enable ANSI on Windows where supported
        print("")
        print("G6 Init Menu")
        print("============")
        print("1) Summary (REAL data, 15s cadence)")
        print("2) Summary (AUTO panels, 15s cadence)")
        print("3) Summary (PANELS only, 15s cadence)")
        print("4) Simulator (emit panels to data/panels)")
        print("5) Kite: test connection")
        print("6) Exit")
        choice = input(f"Select option [{default_choice}]: ").strip() or default_choice

        if choice == "1":
            # Real data: prefer status fields, disable panels json
            env = dict(os.environ)
            env["G6_SUMMARY_PANELS_MODE"] = "off"
            env.setdefault("G6_SUMMARY_REFRESH_SEC", "15")
            cmd = [py, "scripts/summary_view.py", "--refresh", "0.5", "--panels", "off"]
            return _run(cmd, env)
        elif choice == "2":
            env = dict(os.environ)
            env["G6_SUMMARY_PANELS_MODE"] = "auto"
            env.setdefault("G6_SUMMARY_REFRESH_SEC", "15")
            cmd = [py, "scripts/summary_view.py", "--refresh", "0.5", "--panels", "auto"]
            return _run(cmd, env)
        elif choice == "3":
            env = dict(os.environ)
            env["G6_SUMMARY_PANELS_MODE"] = "on"
            env.setdefault("G6_SUMMARY_REFRESH_SEC", "15")
            cmd = [py, "scripts/summary_view.py", "--refresh", "0.5", "--panels", "on"]
            return _run(cmd, env)
        elif choice == "4":
            # Start bridge that mirrors runtime_status.json into per-panel JSONs
            cmd = [py, "scripts/status_to_panels.py", "--status-file", "data/runtime_status.json", "--refresh", "1.0"]
            return _run(cmd)
        elif choice == "5":
            # Prefer running as a module to ensure 'src' package resolves correctly
            cmd = [py, "-m", "src.tools.test_kite_connection"]
            return _run(cmd)
        elif choice == "6":
            print("Bye.")
            return 0
        else:
            print("Invalid choice. Try again.")


if __name__ == "__main__":
    raise SystemExit(menu_loop())
