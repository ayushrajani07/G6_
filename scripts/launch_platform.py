#!/usr/bin/env python
"""Unified launcher for the G6 platform.

Goals:
  * Provide a single entry script that can (optionally) validate/refresh Kite auth
    before starting the orchestrator loop.
  * Offer convenience shortcuts to run summary / panels only modes.
  * Wrap existing preferred runner `scripts/run_orchestrator_loop.py` without
    duplicating loop logic.

Design:
  * Auth step is non-fatal by default; use --require-auth to fail hard if token
    acquisition/validation fails.
  * --auth-only mode performs just the auth validation and exits (0 on success
    / 4 on failure) allowing CI pipelines or pre-flight checks.
  * --no-auth skips auth probe entirely (useful for pure simulation / offline).
  * Summary / Panels flags are thin wrappers that exec the existing scripts.

Exit Codes:
  0 success (or summary/panels subcommand success)
  2 bootstrap failure (propagated from orchestrator runner)
  3 unrecoverable loop exception (propagated)
  4 auth failure when --require-auth or --auth-only
  5 invalid CLI usage / internal error

Note: This script intentionally keeps imports light until after argument parsing
for faster --help responsiveness.
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=os.environ.get("G6_LOG_LEVEL", "INFO"), format=LOG_FORMAT)
logger = logging.getLogger("launch_platform")

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# Lazy import paths (startup_sequence & orchestrator runner) are imported inside functions


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="G6 Unified Launcher")
    p.add_argument("--config", default="config/g6_config.json", help="Config JSON path for orchestrator")
    p.add_argument("--interval", type=float, default=30.0, help="Cycle interval seconds (orchestrator mode)")
    p.add_argument("--cycles", type=int, default=0, help="Max cycles (0=unbounded) mapped to G6_LOOP_MAX_CYCLES if >0")
    p.add_argument("--parallel", action="store_true", help="Enable parallel per-index collection")
    p.add_argument("--auto-snapshots", action="store_true", help="Enable auto snapshots & catalog HTTP")
    p.add_argument("--no-auth", action="store_true", help="Skip Kite auth validation phase")
    p.add_argument("--require-auth", action="store_true", help="Fail (exit 4) if auth validation cannot succeed")
    p.add_argument("--auth-only", action="store_true", help="Only perform auth validation then exit (0/4)")
    p.add_argument("--summary", action="store_true", help="Run summary view instead of orchestrator loop")
    # Stack/observability controls (deprecated): stack is mandatory and brought up via obs_start.ps1 on Windows
    # Removed legacy panels bridge mode (status_to_panels.py); unified summary handles panels internally now.
    # Retain flag stub to avoid breaking old automation; emit warning if used.
    p.add_argument("--panels", action="store_true", help="(Deprecated) Equivalent to --summary; legacy bridge & env toggle removed (auto-detect active)")
    p.add_argument("--dry-run", action="store_true", help="Print planned actions then exit")
    p.add_argument("--concise", action="store_true", help="Force concise logging mode (overrides env)")
    p.add_argument("--verbose", action="store_true", help="Force verbose logging (disables concise mode)")
    p.add_argument("--quiet", action="store_true", help="Suppress most logs; only cycle summaries & errors")
    return p.parse_args(argv)


def ensure_env(args: argparse.Namespace) -> None:
    if args.auto_snapshots:
        os.environ.setdefault("G6_AUTO_SNAPSHOTS", "1")
        os.environ.setdefault("G6_SNAPSHOT_CACHE", "1")
    if args.parallel:
        os.environ.setdefault("G6_PARALLEL_INDICES", "1")
    if os.environ.get("G6_SNAPSHOT_CACHE") == "1" or os.environ.get("G6_CATALOG_HTTP_FORCED") == "1":
        os.environ.setdefault("G6_CATALOG_HTTP", "1")
    if args.cycles > 0 and not os.environ.get("G6_LOOP_MAX_CYCLES"):
        os.environ["G6_LOOP_MAX_CYCLES"] = str(args.cycles)
    # Logging mode precedence: quiet > verbose > concise > existing env
    if args.quiet:
        # Quiet implies concise and lowers root log level later
        os.environ["G6_CONCISE_LOGS"] = "1"
        os.environ.setdefault("G6_QUIET_MODE", "1")
    elif args.verbose:
        os.environ["G6_CONCISE_LOGS"] = "0"
        os.environ.pop("G6_QUIET_MODE", None)
    elif args.concise:
        os.environ["G6_CONCISE_LOGS"] = "1"
        os.environ.pop("G6_QUIET_MODE", None)
    # All stack services are mandatory; do not set G6_INFLUX_OPTIONAL here


def run_auth_validation(require_success: bool) -> bool:
    try:
        from src.orchestrator.startup_sequence import kite_auth_validation  # type: ignore
    except Exception:
        logger.warning("Auth validation unavailable (startup_sequence import failed)")
        return not require_success
    try:
        kite_auth_validation(ctx=None)  # ctx currently unused in implementation
        return True
    except Exception:
        logger.exception("Auth validation raised unexpected exception")
        return False


def run_summary_view() -> int:
    summary_script = _SCRIPT_DIR / "summary" / "app.py"
    if not summary_script.exists():
        logger.error("summary/app.py script missing: %s", summary_script)
        return 5
    cmd = [sys.executable, str(summary_script), "--refresh", "1.0"]
    logger.info("Launching unified summary: %s", ' '.join(cmd))
    return subprocess.call(cmd)


def _warn_panels_flag() -> None:
    if os.environ.get("G6_SUPPRESS_DEPRECATIONS") == "1":
        return
    logger.warning("--panels flag deprecated; behaves like --summary. Remove usage (panels auto-detect is always on).")


def run_orchestrator(args: argparse.Namespace) -> int:
    runner = _SCRIPT_DIR / "run_orchestrator_loop.py"
    if not runner.exists():
        logger.error("orchestrator runner missing: %s", runner)
        return 5
    # Resolve config path robustly so it works from any CWD and common shorthand
    cfg_arg = args.config
    cfg_path = Path(cfg_arg)
    candidates: list[Path] = []
    if cfg_path.is_absolute():
        candidates.append(cfg_path)
    else:
        # Provided a relative path: try project root join first
        candidates.append(_PROJECT_ROOT / cfg_path)
        # If user passed just a filename like 'g6_config.json', also try under 'config/'
        if cfg_path.name == cfg_arg:  # indicates no subdirectories in arg
            candidates.append(_PROJECT_ROOT / 'config' / cfg_path.name)
    cfg_final: Path | None = None
    for p in candidates:
        if p.exists():
            cfg_final = p
            break
    if cfg_final is None:
        logger.error("Config file not found. Tried: %s", ", ".join(str(p) for p in candidates))
        # Fall back to first candidate so downstream error carries a concrete path
        cfg_final = candidates[0]
    else:
        logger.info("Resolved config path: %s", cfg_final)
    cmd = [sys.executable, str(runner), "--config", str(cfg_final), "--interval", str(args.interval)]
    if args.cycles:
        cmd.extend(["--cycles", str(args.cycles)])
    if args.parallel:
        cmd.append("--parallel")
    if args.auto_snapshots:
        cmd.append("--auto-snapshots")
    logger.info("Launching orchestrator: %s", ' '.join(cmd))
    try:
        return subprocess.call(cmd)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received; exiting launcher gracefully.")
        return 0


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    ensure_env(args)
    # Adjust runtime logging levels for quiet mode after env applied
    if os.environ.get("G6_QUIET_MODE") == "1":
        # Raise root level to WARNING; selectively allow cycle summary logger if needed
        logging.getLogger().setLevel(logging.WARNING)
        # Collector cycle summary uses logger.info; introduce lightweight filter to allow specific patterns
        class _CycleSummaryFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover (simple predicate)
                msg = record.getMessage()
                if "CYCLE" in msg or "cycle" in msg.lower():
                    return True
                return record.levelno >= logging.WARNING
        logging.getLogger().addFilter(_CycleSummaryFilter())
        # Secondary filter: drop any remaining TRACE lines that slipped through (defense-in-depth)
        class _NoTraceFilter(logging.Filter):
            def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover
                m = record.getMessage()
                if m.startswith("TRACE ") or " TRACE " in m:
                    return False
                return True
        logging.getLogger().addFilter(_NoTraceFilter())

    # Bring up Observability Stack via PowerShell (Windows) and enforce mandatory services
    try:
        if os.name == 'nt':
            ps1 = _SCRIPT_DIR / 'obs_start.ps1'
            if not ps1.exists():
                logger.error("obs_start.ps1 missing: %s", ps1)
                return 3
            cmd = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(ps1)]
            logger.info("[launcher] Starting observability stack via obs_start.ps1")
            subprocess.run(cmd, cwd=str(_PROJECT_ROOT), check=False, timeout=180)
        else:
            logger.warning("[launcher] obs_start.ps1 is Windows-only; ensure Prometheus, InfluxDB, and Grafana are running")
        # Verify all services are healthy after attempted start
        from scripts.auto_resolve_stack import ensure_stack, print_summary  # type: ignore
        stack = ensure_stack(auto_start=False)
        print_summary(stack)
        if not (stack.prometheus.ok and stack.grafana.ok and stack.influx.ok):
            logger.error("[launcher] Observability stack not healthy (all mandatory). prom=%s graf=%s influx=%s", stack.prometheus.ok, stack.grafana.ok, stack.influx.ok)
            return 3
    except Exception:
        logger.exception("[launcher] Stack bring-up/verification failed")
        return 3

    planned = []
    if not args.no_auth and not args.summary and not args.panels:
        planned.append("auth_validation")
    if args.auth_only:
        planned.append("auth_only_exit")
    elif args.summary:
        planned.append("summary_app")
    elif args.panels:
        planned.append("deprecated_panels_flag")
    else:
        planned.append("orchestrator_loop")

    if args.dry_run:
        print("Planned actions:", ", ".join(planned))
        return 0

    # Auth validation phase
    if not args.no_auth:
        logger.info("[launcher] Starting auth validation phase (require_success=%s)", args.require_auth or args.auth_only)
        ok = run_auth_validation(require_success=(args.require_auth or args.auth_only))
        if not ok and (args.require_auth or args.auth_only):
            logger.error("[launcher] Auth validation failed (exiting)")
            return 4
        if args.auth_only:
            logger.info("[launcher] Auth-only mode complete (success=%s)", ok)
            return 0 if ok else 4

    # Dispatch to chosen mode
    if args.summary:
        return run_summary_view()
    if args.panels:
        _warn_panels_flag()
        return run_summary_view()
    return run_orchestrator(args)

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
