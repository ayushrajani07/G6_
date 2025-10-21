from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import Any

# =============================
# G6 Unified Summary Init Menu
# =============================
# This menu now centers around scripts/summary/app.py (unified summary view) and
# exposes explicit variants, curated layout mode (legacy summary_view removed),
# panels toggles, and data/diagnostic utilities (CSV audit/backfill, simulator).
#
# Key Environment Flags surfaced:
#  - G6_SUMMARY_PANELS_MODE / panels CLI arg (app auto-detect still supported)
#  - G6_SUMMARY_READ_PANELS (whether to consume existing panels artifacts)
#  - G6_SUMMARY_REFRESH_SEC (base cadence)
#  - G6_SUMMARY_CURATED_MODE=1 (enable curated adaptive layout)
#  - G6_EXPIRY_EXPAND_CONFIG=1 (collector expiry expansion – informational toggle here)
#
# Unified summary script (scripts/summary/app.py) provides all modes (plain / Rich / curated).
#
# Utilities integrated:
#  - CSV Audit (scripts/csv_audit.py)
#  - CSV Backfill (scripts/csv_backfill.py) DRY-RUN and EXEC modes
#  - Status Simulator only (dev_tools simulate-status)
#  - Quick Unified Collectors Cycle (if launch_platform is extended later)
#
# This structure is intentionally linear for clarity; advanced grouping kept minimal
# to avoid nested menus explosion.

# Ensure project root on sys.path using centralized helper when available
try:
    from src.utils.path_utils import ensure_sys_path  # type: ignore
    ensure_sys_path()
except Exception:
    try:
        _this_dir = os.path.dirname(os.path.abspath(__file__))
        _proj_root = os.path.dirname(_this_dir)
        if _proj_root and _proj_root not in sys.path:
            sys.path.insert(0, _proj_root)
        from src.utils.path_utils import ensure_sys_path  # type: ignore
        ensure_sys_path()
    except Exception:
        pass


# Resolve important paths (robust whether CWD is repo root or scripts/)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ_ROOT = os.path.dirname(_SCRIPT_DIR)

def _path(*parts: str) -> str:
    return os.path.join(_PROJ_ROOT, *parts)

# Canonical script file paths
SUMMARY_APP = _path("scripts", "summary", "app.py")
LEGACY_SUMMARY = _path("scripts", "summary", "app.py")  # retained variable name for backward compatibility
STATUS_SIM = _path("scripts", "status_simulator.py")
DEV_TOOLS = _path("scripts", "dev_tools.py")
CSV_AUDIT = _path("scripts", "csv_audit.py")
CSV_BACKFILL = _path("scripts", "csv_backfill.py")
PANELS_BRIDGE = _path("scripts", "status_to_panels.py")  # legacy / bridge for panels artifacts


def _python_exe() -> str:
    # Prefer current venv python
    try:
        return sys.executable or "python"
    except Exception:
        return "python"


def _merge_env(base: dict[str, str] | None = None, add: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(base or os.environ)
    if add:
        for k, v in add.items():
            if v is not None:
                env[str(k)] = str(v)
    return env


def _run(cmd: list[str], env: dict[str, str] | None = None) -> int:
    try:
        # On Windows PowerShell, use direct subprocess without shell to preserve Ctrl+C behavior
        proc = subprocess.Popen(cmd, env=env or os.environ.copy(), cwd=_PROJ_ROOT)
        proc.wait()
        return proc.returncode or 0
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        print(f"Failed to start: {' '.join(cmd)} -> {e}")
        return 2


def _spawn(cmd: list[str], env: dict[str, str] | None = None, quiet: bool = True) -> subprocess.Popen[Any]:
    """Spawn a background process, optionally silencing stdio.

    Avoid shell=True to preserve Ctrl+C behavior and keep types precise to satisfy mypy.
    """
    stdout = subprocess.DEVNULL if quiet else None
    stderr = subprocess.DEVNULL if quiet else None
    # Avoid shell=True; keep Ctrl+C behavior
    return subprocess.Popen(
        cmd,
        env=env or os.environ.copy(),
        stdout=stdout,
        stderr=stderr,
    )


def _ensure_panels_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    sinks = env.get("G6_OUTPUT_SINKS", "stdout,logging")
    if "panels" not in [t.strip().lower() for t in sinks.split(",") if t.strip()]:
        sinks = sinks + ",panels"
    env.update({
        "G6_OUTPUT_SINKS": sinks,
        "G6_PANELS_DIR": env.get("G6_PANELS_DIR", os.path.join("data", "panels")),
    })
    if extra:
        env.update(extra)
    return env


def _stop_background_processes() -> int:
    """Stop typical background processes started for demo flows.

    Targets:
    - (legacy) status_to_panels.py (removed; panels handled by unified summary)
      - scripts/dev_tools.py simulate-status (simulator)
      - scripts/status_simulator.py (if running in loop)

    Uses psutil if available for robust matching and termination.
    """
    patterns = (
        # legacy bridge removed
        "scripts/dev_tools.py",
        "simulate-status",
        "scripts/status_simulator.py",
    )
    killed: int = 0
    try:
        import psutil  # type: ignore
    except Exception:
        print("psutil not available. Please stop processes via Task Manager or install psutil.")
        print("Look for python processes running 'python -m scripts.summary.app' or dev_tools.py simulate-status.")
        return 1
    try:
        for p in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmd = p.info.get("cmdline") or []
                # Normalize to strings
                cmd_str = " ".join(str(x) for x in cmd)
                if any(tok in cmd_str for tok in patterns):
                    print(f"Stopping PID {p.pid}: {cmd_str}")
                    p.terminate()
                    try:
                        p.wait(timeout=1.0)
                    except Exception:
                        p.kill()
                    killed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as e:
        print(f"Error while scanning processes: {e}")
        return 2
    print(f"Stopped {killed} process(es).")
    return 0


def _others_menu(py: str) -> int:
    while True:
        print("\nAdvanced / Legacy / Utilities")
        print("================================")
        print("1) Legacy Summary (Plain, Panels OFF)")
        print("2) Legacy Summary (Rich, Panels OFF)")
        print("3) Legacy Summary (Panels Mode, Plain)")
        print("4) Legacy Summary (Panels Mode, Rich)")
        print("5) Panels One-shot Demo (Simulate + Legacy Plain)")
        print("6) CSV Audit (today)")
        print("7) CSV Backfill DRY-RUN (today)")
        print("8) CSV Backfill EXEC (today)")
        print("9) Simulator Only (loop)")
        print("10) Test Kite Connection")
        print("11) Stop Background Processes")
        print("12) Toggle Expiry Expansion (show state)")
        print("0) Back")
        choice = input("Select option [0]: ").strip() or "0"

        if choice == "1":
            return _run([py, LEGACY_SUMMARY, "--no-rich", "--panels", "off"], None)
        if choice == "2":
            return _run([py, LEGACY_SUMMARY, "--refresh", "0.5", "--panels", "off"], None)
        if choice == "3":
            # Panels mode now auto-detected; pass '--panels on' only for backward CLI compat
            return _run([py, LEGACY_SUMMARY, "--no-rich", "--panels", "on"], None)
        if choice == "4":
            return _run([py, LEGACY_SUMMARY, "--refresh", "0.5", "--panels", "on"], None)
        if choice == "5":
            print("Running Panels One-shot Demo (simulation + legacy plain)…")
            sim_cmd = [py, STATUS_SIM, "--status-file", "data/runtime_status_demo.json", "--indices", "NIFTY,BANKNIFTY,FINNIFTY,SENSEX", "--interval", "60", "--refresh", "0.1", "--open-market", "--with-analytics", "--cycles", "1"]
            rc = _run(sim_cmd)
            if rc != 0: return rc
            return _run([py, LEGACY_SUMMARY, "--no-rich", "--refresh", "1", "--status-file", "data/runtime_status_demo.json"], None)
        if choice == "6":
            today = time.strftime('%Y-%m-%d')
            return _run([py, CSV_AUDIT, "--date", today, "--pretty", "--max-steps", "5", "--step-size", "50"], None)
        if choice == "7":
            today = time.strftime('%Y-%m-%d')
            return _run([py, CSV_BACKFILL, "--date", today, "--dry-run", "--pretty"], None)
        if choice == "8":
            today = time.strftime('%Y-%m-%d')
            return _run([py, CSV_BACKFILL, "--date", today, "--pretty"], None)
        if choice == "9":
            print("Starting status simulator (loop)… Ctrl+C to stop.")
            return _run([py, DEV_TOOLS, "simulate-status", "--status-file", "data/runtime_status.json", "--interval", "60", "--refresh", "1.0", "--open-market", "--with-analytics"], None)
        if choice == "10":
            return _run([py, "-m", "src.tools.test_kite_connection"], None)
        if choice == "11":
            return _stop_background_processes()
        if choice == "12":
            cur = os.getenv("G6_EXPIRY_EXPAND_CONFIG", "1")
            new = "0" if cur.lower() in ("1","true","yes","on") else "1"
            os.environ["G6_EXPIRY_EXPAND_CONFIG"] = new
            print(f"G6_EXPIRY_EXPAND_CONFIG toggled: {cur} -> {new}")
            continue
        if choice == "0":
            return 0
        print("Invalid choice. Try again.")


def menu_loop() -> int:
    py = _python_exe()
    default_choice = "1"
    while True:
        try:
            os.system("")
        except Exception:
            pass
        print("\nG6 Unified Summary Menu")
        print("========================")
        print("1) Unified Summary (Panels Auto, Rich)")
        print("2) Unified Summary (Panels OFF, Rich)")
        print("3) Unified Summary (Curated Layout, Panels Auto)")
        print("4) Unified Summary (Plain Fallback, no-rich)")
        print("5) Unified Summary (Run 10 cycles then exit)")
        print("6) Simulator + Unified Summary (Panels Auto)")
        print("7) Web Dashboard (Live)")
        print("8) Web Dashboard (Simulator)")
        print("9) FAST STACK: Sim + Panels Bridge + Summary (0.5s)")
        print("10) FAST STACK: Sim + Summary (no bridge, 0.5s)")
        print("11) Advanced / Legacy / Utilities …")
        print("12) DIAGNOSTIC STACK: Sim + Summary (debug+metrics)")
        print("13) FAST STACK: Sim + Summary + SSE Overlay (live panels)")
        print("14) LIVE SSE ONLY: Summary + SSE Overlay (no simulator)")
        print("0) Exit")
        choice = input(f"Select option [{default_choice}]: ").strip() or default_choice

        if choice == "1":
            env = _ensure_panels_env({})
            status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
            return _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
        if choice == "2":
            env = _merge_env()
            status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
            return _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5", "--panels", "off"], env)
        if choice == "3":
            env = _ensure_panels_env({"G6_SUMMARY_CURATED_MODE": "1"})
            status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
            return _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
        if choice == "4":
            env = _merge_env()
            status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
            return _run([py, SUMMARY_APP, "--status-file", status_abs, "--no-rich", "--panels", "off", "--refresh", "1"], env)
        if choice == "5":
            env = _ensure_panels_env({})
            status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
            return _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5", "--cycles", "10"], env)
        if choice == "6":
            print("Starting simulator in background… Ctrl+C to stop when UI exits.")
            sim_cmd = [py, DEV_TOOLS, "simulate-status", "--status-file", "data/runtime_status.json", "--interval", "60", "--refresh", "1.0", "--open-market", "--with-analytics"]
            p_sim0 = _spawn(sim_cmd, quiet=True)
            time.sleep(0.3)
            env = _ensure_panels_env({})
            try:
                status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
                rc = _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
            finally:
                try:
                    if p_sim0.poll() is None:
                        p_sim0.terminate()
                        try:
                            p_sim0.wait(timeout=1.0)
                        except Exception:
                            p_sim0.kill()
                except Exception:
                    pass
            return rc
        if choice == "7":
            metrics_url = os.getenv("G6_METRICS_ENDPOINT", os.getenv("G6_METRICS_URL", "http://127.0.0.1:9108/metrics"))
            env = _merge_env(add={"G6_METRICS_ENDPOINT": metrics_url, "G6_METRICS_URL": metrics_url})
            return _run([py, "-m", "uvicorn", "src.web.dashboard.app:app", "--host", "127.0.0.1", "--port", os.getenv("G6_WEB_PORT", "9300")], env)
        if choice == "8":
            print("Starting mock collectors (metrics) in background… Ctrl+C to stop when UI exits.")
            dash_cmd = [py, "scripts/dev_tools.py", "dashboard", "--status-file", "data/runtime_status.json", "--interval", "60", "--cycles", "0", "--sleep-between", "1.0"]
            p_dash = _spawn(dash_cmd, quiet=True)
            time.sleep(0.8)
            metrics_url = os.getenv("G6_METRICS_ENDPOINT", os.getenv("G6_METRICS_URL", "http://127.0.0.1:9108/metrics"))
            env = _merge_env(add={"G6_METRICS_ENDPOINT": metrics_url, "G6_METRICS_URL": metrics_url})
            try:
                rc = _run([py, "-m", "uvicorn", "src.web.dashboard.app:app", "--host", "127.0.0.1", "--port", os.getenv("G6_WEB_PORT", "9300")], env)
            finally:
                try:
                    if p_dash.poll() is None:
                        p_dash.terminate()
                        try:
                            p_dash.wait(timeout=1.0)
                        except Exception:
                            p_dash.kill()
                except Exception:
                    pass
            return rc
        if choice == "9":
            # Fast stack with simulator + panels bridge (background) + summary app
            print("Starting FAST STACK (simulator + panels bridge + summary)… Ctrl+C exits summary and cleans up.")
            sim_cmd = [py, DEV_TOOLS, "simulate-status", "--status-file", "data/runtime_status.json", "--interval", "60", "--refresh", "0.5", "--open-market", "--with-analytics"]
            bridge_cmd = [py, PANELS_BRIDGE, "--status-file", "data/runtime_status.json", "--refresh", "0.5"]
            p_sim: subprocess.Popen[Any] | None = None
            p_bridge: subprocess.Popen[Any] | None = None
            try:
                p_sim = _spawn(sim_cmd, quiet=True)
                time.sleep(0.25)
                env = _ensure_panels_env({})
                # Bridge optional: ensure script exists before spawning
                if os.path.exists(PANELS_BRIDGE):
                    p_bridge = _spawn(bridge_cmd, quiet=True)
                    time.sleep(0.25)
                else:
                    print("Panels bridge script not found; continuing without it.")
                status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
                rc = _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
            finally:
                for proc in (p_bridge, p_sim):
                    try:
                        if proc and proc.poll() is None:
                            proc.terminate()
                            try:
                                proc.wait(timeout=1.0)
                            except Exception:
                                proc.kill()
                    except Exception:
                        pass
            return rc
        if choice == "10":
            # Fast stack without panels bridge (slightly lighter) + summary
            print("Starting FAST STACK (simulator + summary)… Ctrl+C exits summary and cleans up.")
            sim_cmd = [py, DEV_TOOLS, "simulate-status", "--status-file", "data/runtime_status.json", "--interval", "60", "--refresh", "0.5", "--open-market", "--with-analytics"]
            p_sim2: subprocess.Popen[Any] | None = None
            try:
                p_sim2 = _spawn(sim_cmd, quiet=True)
                time.sleep(0.25)
                env = _ensure_panels_env({})  # allow panels mode auto-detect if artifacts appear
                status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
                rc = _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
            finally:
                try:
                    if p_sim2 and p_sim2.poll() is None:
                        p_sim2.terminate()
                        try:
                            p_sim2.wait(timeout=1.0)
                        except Exception:
                            p_sim2.kill()
                except Exception:
                    pass
            return rc
        if choice == "11":
            return _others_menu(py)
        if choice == "12":
            print("Starting DIAGNOSTIC STACK (simulator + summary with debug flags)…")
            sim_cmd = [py, DEV_TOOLS, "simulate-status", "--status-file", "data/runtime_status.json", "--interval", "60", "--refresh", "0.5", "--open-market", "--with-analytics"]
            p_simd: subprocess.Popen[Any] | None = None
            try:
                p_simd = _spawn(sim_cmd, quiet=True)
                time.sleep(0.3)
                env = _ensure_panels_env({
                    "G6_SUMMARY_BUILD_MODEL": "1",
                    "G6_SUMMARY_DEBUG_UPDATES": "1",
                    "G6_SUMMARY_DEBUG_LOG": "1",
                    "G6_UNIFIED_METRICS": "1",
                    "G6_PANELS_SSE_DEBUG": "1",
                })
                status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
                rc = _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
            finally:
                try:
                    if p_simd and p_simd.poll() is None:
                        p_simd.terminate()
                        try:
                            p_simd.wait(timeout=1.0)
                        except Exception:
                            p_simd.kill()
                except Exception:
                    pass
            return rc
        if choice == "13":
            # Fast stack with SSE overlay (no legacy panels bridge). Assumes an SSE endpoint is available.
            print("Starting FAST STACK (simulator + summary + SSE overlay)… Ctrl+C exits summary and cleans up.")
            sim_cmd = [py, DEV_TOOLS, "simulate-status", "--status-file", "data/runtime_status.json", "--interval", "60", "--refresh", "0.5", "--open-market", "--with-analytics"]
            p_sim3: subprocess.Popen[Any] | None = None
            try:
                p_sim3 = _spawn(sim_cmd, quiet=True)
                time.sleep(0.3)
                # Default SSE URL heuristic (aligns with typical dev server 9315 or 9300 events endpoint). Allow override if already set.
                default_sse = os.getenv("G6_PANELS_SSE_URL") or os.getenv("G6_SUMMARY_SSE_URL") or "http://127.0.0.1:9315/events"
                env = _ensure_panels_env({
                    "G6_PANELS_SSE_URL": default_sse,
                    "G6_PANELS_SSE_OVERLAY": "1",
                    "G6_UNIFIED_METRICS": "1",
                })
                status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
                rc = _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
            finally:
                try:
                    if p_sim3 and p_sim3.poll() is None:
                        p_sim3.terminate()
                        try:
                            p_sim3.wait(timeout=1.0)
                        except Exception:
                            p_sim3.kill()
                except Exception:
                    pass
            return rc
        if choice == "14":
            # Live SSE only (no simulator). Requires external process populating SSE endpoint.
            print("Starting LIVE SSE ONLY Summary (no simulator)… Ensure your SSE endpoint is running.")
            default_sse = os.getenv("G6_PANELS_SSE_URL") or os.getenv("G6_SUMMARY_SSE_URL") or "http://127.0.0.1:9315/events"
            env = _ensure_panels_env({
                "G6_PANELS_SSE_URL": default_sse,
                "G6_PANELS_SSE_OVERLAY": "1",
                "G6_UNIFIED_METRICS": "1",
                # Avoid reading panels artifacts if they could be stale; overlay supplies live data.
                "G6_SUMMARY_READ_PANELS": "false",
            })
            status_abs = os.path.join(_PROJ_ROOT, 'data', 'runtime_status.json')
            return _run([py, SUMMARY_APP, "--status-file", status_abs, "--refresh", "0.5"], env)
        if choice == "0":
            print("Bye.")
            return 0
        print("Invalid choice. Try again.")


if __name__ == "__main__":
    raise SystemExit(menu_loop())

# Minimal exported MENU structure for lightweight import smoke tests.
# The interactive implementation relies on menu_loop(), but tests only verify
# presence of a non-empty MENU iterable. Keep this concise to avoid executing
# interactive logic during import. Update if additional metadata fields are
# later required by tests.
MENU = [
    {"id": 1, "label": "Unified Summary (Rich Auto)", "entry": "summary_rich_auto"},
    {"id": 2, "label": "Unified Summary (Panels Off)", "entry": "summary_rich_nopanels"},
]
