"""Development maintenance utilities.

This script provides quick actions for:
  * Purging stale __pycache__ and *.pyc bytecode (helps after indentation / syntax fixes)
  * Verifying syntax import of critical modules (e.g. scripts.summary.app)
  * Optionally running a focused pytest subset before the full suite

Usage (PowerShell examples):

  python scripts/maintenance.py --purge-cache --check-summary
  python scripts/maintenance.py --purge-cache --run tests/test_cadence.py
  python scripts/maintenance.py --all

Flags:
  --purge-cache      Remove all __pycache__ directories and *.pyc files under repo root.
  --check-summary    Attempt import of scripts.summary.app and report success/failure.
  --run <testpath>   Run pytest for a specific test file (fast feedback).
  --full             Run full pytest suite (after optional purge).
  --all              Shorthand: purge + check-summary + full test run.
  --dry-run          Show what would be done without executing destructive steps.

Exit Codes:
  0 success; non-zero on first failure encountered.
"""
from __future__ import annotations

import argparse
import importlib.util
import pathlib
import shutil
import subprocess
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def purge_cache(dry: bool) -> None:
    removed = 0
    for p in REPO_ROOT.rglob("__pycache__"):
        if p.is_dir():
            if dry:
                print(f"[dry-run] would remove dir {p}")
            else:
                shutil.rmtree(p, ignore_errors=True)
            removed += 1
    for pyc in REPO_ROOT.rglob("*.pyc"):
        if dry:
            print(f"[dry-run] would remove file {pyc}")
        else:
            try: pyc.unlink()
            except Exception: pass
            removed += 1
    print(f"[maintenance] cache purge complete (entries={removed})")


def check_summary_app() -> bool:
    target = REPO_ROOT / 'scripts' / 'summary' / 'app.py'
    if not target.exists():
        print(f"[maintenance] summary app missing: {target}")
        return False
    try:
        spec = importlib.util.spec_from_file_location('summary_app_check', target)
        mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore[call-arg]
        ok = hasattr(mod, 'compute_cadence_defaults')
        print(f"[maintenance] imported summary app OK (compute_cadence_defaults={ok})")
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[maintenance] ERROR importing summary app: {e}")
        return False


def run_pytest(args: list[str]) -> int:
    cmd = [sys.executable, '-m', 'pytest'] + args
    print(f"[maintenance] running: {' '.join(cmd)}")
    try:
        return subprocess.run(cmd, cwd=REPO_ROOT).returncode
    except KeyboardInterrupt:
        return 130


def main() -> int:
    ap = argparse.ArgumentParser(description="Dev maintenance helper")
    ap.add_argument('--purge-cache', action='store_true')
    ap.add_argument('--check-summary', action='store_true')
    ap.add_argument('--run', metavar='TESTPATH', help='Run specific test path (pytest)')
    ap.add_argument('--full', action='store_true', help='Run full test suite')
    ap.add_argument('--all', action='store_true', help='Shortcut: purge + check-summary + full')
    ap.add_argument('--dry-run', action='store_true')
    ns = ap.parse_args()

    if ns.all:
        ns.purge_cache = True
        ns.check_summary = True
        ns.full = True

    if ns.purge_cache:
        purge_cache(dry=ns.dry_run)

    summary_ok = True
    if ns.check_summary:
        summary_ok = check_summary_app()
        if not summary_ok and not (ns.run or ns.full):
            return 1

    if ns.run:
        rc = run_pytest([ns.run])
        if rc != 0:
            return rc

    if ns.full:
        rc = run_pytest(['-q'])
        if rc != 0:
            return rc

    return 0 if summary_ok else 1


if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
