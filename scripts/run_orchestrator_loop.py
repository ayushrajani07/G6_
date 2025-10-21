#!/usr/bin/env python
"""Preferred orchestration loop runner (replaces legacy unified_main entry).

Features:
    * Uses bootstrap_runtime + run_loop abstraction (unified collectors always active)
  * Honors G6_LOOP_MAX_CYCLES (or --cycles CLI mapped to env) for bounded runs
  * Optional auto snapshots enablement (--auto-snapshots) convenience
  * Clean metrics server shutdown

CLI cycles vs env precedence:
  If --cycles > 0 we set G6_LOOP_MAX_CYCLES unless already provided.

Exit Codes:
  0 success
  2 bootstrap failure
  3 unrecoverable cycle exception
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.config.runtime_config import get_runtime_config
from src.orchestrator.bootstrap import bootstrap_runtime  # type: ignore
from src.orchestrator.context import RuntimeContext  # type: ignore
from src.orchestrator.cycle import run_cycle  # type: ignore
from src.orchestrator.loop import run_loop  # type: ignore
from src.orchestrator.startup_sequence import run_startup_sequence  # type: ignore

try:
    from src.collectors.helpers.cycle_tables import flush_deferred_cycle_tables  # type: ignore
except Exception:  # pragma: no cover
    def flush_deferred_cycle_tables():  # type: ignore
        pass

LOG_FORMAT = "[%(asctime)s] %(levelname)s %(name)s: %(message)s"
logging.basicConfig(level=os.environ.get("G6_LOG_LEVEL", "INFO"), format=LOG_FORMAT)
logger = logging.getLogger("run_orchestrator_loop")

def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Orchestrator Loop Runner")
    p.add_argument("--config", default="config/g6_config.json", help="Config JSON path")
    p.add_argument("--interval", type=float, default=30.0, help="Cycle interval seconds")
    p.add_argument("--cycles", type=int, default=0, help="Number of cycles (0=unbounded)")
    p.add_argument("--auto-snapshots", action="store_true", help="Enable auto snapshots (sets env toggle)")
    p.add_argument("--parallel", action="store_true", help="Enable parallel per-index collection")
    return p.parse_args(argv)

def _load_env_overlay() -> None:
    """Best-effort .env overlay loader.

    Prefer python-dotenv when available; otherwise parse simple KEY=VALUE lines.
    Does not overwrite existing explicit environment variables.
    """
    try:
        from dotenv import load_dotenv  # type: ignore
        load_dotenv()
        return
    except Exception:
        pass
    env_path = _PROJECT_ROOT / '.env'
    try:
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8').splitlines():
                s = line.strip()
                if not s or s.startswith('#') or '=' not in s:
                    continue
                k, v = s.split('=', 1)
                k = k.strip(); v = v.strip()
                if k and os.environ.get(k) is None:
                    os.environ[k] = v
    except Exception:
        # non-fatal
        pass

def _maybe_auth_preflight() -> bool:
    """Ensure Kite auth token exists; trigger interactive login if missing.

    Returns True if OK to proceed (token present or acquired), False to abort.

    Safeguards:
    - Skips during tests (PYTEST_CURRENT_TEST set)
    - Can be disabled via G6_DISABLE_AUTH_PREFLIGHT=1
    - Runs when KITE_ACCESS_TOKEN missing OR API credentials are incomplete
    """
    if os.environ.get('G6_DISABLE_AUTH_PREFLIGHT') in ('1','true','yes','on'):
        return True
    if 'PYTEST_CURRENT_TEST' in os.environ:
        return True
    # Load any .env first so we detect keys if present
    _load_env_overlay()
    have_key = bool(os.environ.get('KITE_API_KEY'))
    have_secret = bool(os.environ.get('KITE_API_SECRET'))
    have_token = bool(os.environ.get('KITE_ACCESS_TOKEN'))
    if have_token:
        return True  # already authenticated
    # If credentials are missing or token absent, launch token manager (it will prompt and persist to .env)
    if not (have_key and have_secret):
        logger.info('Kite credentials missing; launching token manager to capture API key/secret and token...')
    else:
        logger.info('Kite token missing; launching login flow (token manager)...')
    # Invoke token manager in no-autorun mode to just acquire token
    cmd = [sys.executable, '-m', 'src.tools.token_manager', '--no-autorun']
    try:
        rc = os.spawnv(os.P_WAIT, sys.executable, cmd)  # type: ignore[arg-type]
    except Exception:
        # Fallback to subprocess if spawnv not applicable on platform
        import subprocess  # lazy
        try:
            rc = subprocess.call(cmd)
        except Exception:
            rc = 1
    if int(rc) != 0:
        logger.error('Token manager did not complete successfully (rc=%s)', rc)
        return False
    # Reload env from .env so this process sees the fresh token
    _load_env_overlay()
    # Ensure we now have both creds and token
    if not (os.environ.get('KITE_API_KEY') and os.environ.get('KITE_API_SECRET')):
        logger.error('Credentials still missing after token manager run')
        return False
    if not os.environ.get('KITE_ACCESS_TOKEN'):
        logger.error('Token acquisition reported success but KITE_ACCESS_TOKEN still missing in env')
        return False
    logger.info('Kite token acquired. Continuing startup...')
    return True

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


def build_cycle_fn():
    def _fn(ctx: RuntimeContext):  # unified collectors always active
        run_cycle(ctx)
    return _fn


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    ensure_env(args)
    # Auth preflight (interactive prompt if Kite token missing)
    if not _maybe_auth_preflight():
        return 2
    try:
        ctx, metrics_stop = bootstrap_runtime(args.config)
    except Exception:
        logger.exception("Bootstrap failed")
        return 2

    # Invoke ordered startup sequence (non-fatal) before loop
    try:
        run_startup_sequence(ctx)
    except Exception:
        logger.exception("Startup sequence encountered an unexpected error (continuing)")

    # Heuristic index params fallback (mirrors run_live)
    try:
        raw_cfg = ctx.config.raw if hasattr(ctx.config, 'raw') else {}
        if ctx.index_params is None:
            idx_params = raw_cfg.get('index_params') or raw_cfg.get('indices') or {}
            if isinstance(idx_params, dict) and idx_params:
                ctx.index_params = idx_params  # type: ignore[assignment]
            else:
                logger.warning("No index_params found in config; cycles may no-op")
    except Exception:
        logger.debug("Index params extraction failed", exc_info=True)

    if args.auto_snapshots and not os.environ.get('G6_AUTO_SNAPSHOTS'):
        os.environ['G6_AUTO_SNAPSHOTS'] = '1'

    cycle_fn = build_cycle_fn()
    rcfg = get_runtime_config(refresh=True)
    effective_interval = args.interval if args.interval != 30.0 else rcfg.loop.interval_seconds
    # If CLI interval explicitly provided (different from default), prefer it and update runtime config (one-off)
    if args.interval != 30.0 and args.interval != rcfg.loop.interval_seconds:
        # Rebuild singleton with overridden interval (non-invasive); this keeps future adopters consistent
        os.environ['G6_LOOP_INTERVAL_SECONDS'] = str(args.interval)
        rcfg = get_runtime_config(refresh=True)
        effective_interval = rcfg.loop.interval_seconds
    logger.info(
        "Starting orchestrator loop interval=%.2fs parallel=%s auto_snapshots=%s max_cycles_env=%s",
        effective_interval,
        args.parallel,
        bool(os.environ.get('G6_AUTO_SNAPSHOTS')),
        os.environ.get('G6_LOOP_MAX_CYCLES'),
    )
    # SINGLE_HEADER_MODE: emit daily header once centrally (concise mode expectation)
    if os.environ.get('G6_SINGLE_HEADER_MODE','').lower() in ('1','true','yes','on'):
        try:
            import datetime
            # Use timezone-aware UTC date to avoid naive now() (tests forbid naive usage)
            today_str = datetime.datetime.now(datetime.UTC).strftime('%d-%b-%Y')
            if os.environ.get('G6_COMPACT_BANNERS','').lower() in ('1','true','yes','on'):
                logger.info("DAILY OPTIONS COLLECTION LOG %s", today_str)
            else:
                header = ("\n" + "="*70 + f"\n        DAILY OPTIONS COLLECTION LOG — {today_str}\n" + "="*70 + "\n")
                logger.info(header)
        except Exception:
            logger.debug('single_header_mode_emit_failed', exc_info=True)

    try:
        run_loop(ctx, cycle_fn=cycle_fn, interval=effective_interval)
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received – exiting cleanly (code 0)")
    except Exception:
        logger.exception("Unrecoverable loop exception")
        return 3
    finally:
        # Graceful shutdown: close sinks/providers to stop any background threads (e.g., Influx retries)
        try:
            prov = getattr(ctx, 'providers', None)
            if prov and hasattr(prov, 'close'):
                try:
                    prov.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            _csv = getattr(ctx, 'csv_sink', None)
            if _csv is not None and hasattr(_csv, 'close'):
                try:
                    _csv.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            _influx = getattr(ctx, 'influx_sink', None)
            if _influx is not None and hasattr(_influx, 'close'):
                try:
                    _influx.close()
                except Exception:
                    pass
        except Exception:
            pass
        try:
            if callable(metrics_stop):  # type: ignore[call-arg]
                metrics_stop()
        except Exception:
            pass
    logger.info("Loop complete")
    # Final flush of deferred tables if enabled
    try:
        flush_deferred_cycle_tables()
    except Exception:
        logger.debug('flush_deferred_cycle_tables_failed', exc_info=True)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
