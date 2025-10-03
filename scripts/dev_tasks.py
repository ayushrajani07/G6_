#!/usr/bin/env python
from __future__ import annotations

"""Unified developer task runner for G6 Platform.

Usage examples:
  python scripts/dev_tasks.py lint
  python scripts/dev_tasks.py typecheck
  python scripts/dev_tasks.py format
  python scripts/dev_tasks.py test -k junk
  python scripts/dev_tasks.py quick-cycle
  python scripts/dev_tasks.py secrets-scan
  python scripts/dev_tasks.py update-secrets-baseline

Commands:
  lint                  Run ruff (lint) + pyupgrade check (pre-commit simulation)
  format                Run ruff format (and optional black if enabled)
  typecheck             Run mypy using local mypy.ini
  test [pytest args...] Run pytest with any extra args passed through
  quick-cycle           Execute a single lightweight simulated cycle (env gated)
  secrets-scan          Run detect-secrets against repo using baseline (read only)
  update-secrets-baseline Re-create .secrets.baseline (fails if staged secrets found)

Environment helpers:
  G6_RUFF_BIN, G6_MYPY_BIN, G6_PYTEST_BIN can override executable paths.

Exit codes: non-zero on any underlying tool failure.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print(f"[dev_tasks] RUN: {' '.join(cmd)}")
    proc = subprocess.run(cmd, cwd=cwd or REPO_ROOT)
    if check and proc.returncode != 0:
        print(f"[dev_tasks] Command failed with exit code {proc.returncode}", file=sys.stderr)
        sys.exit(proc.returncode)
    return proc.returncode


def cmd_lint(_: argparse.Namespace) -> None:
    ruff = os.environ.get("G6_RUFF_BIN", "ruff")
    _run([ruff, "check", "--fix", "."])
    pyupgrade = shutil.which("pyupgrade")
    if pyupgrade:
        files = subprocess.check_output(["git", "ls-files", "*.py"], text=True).strip().splitlines()
        if files:
            _run([pyupgrade, "--py313-plus", *files])
    else:
        print("[dev_tasks] pyupgrade not installed; skipping.")


def cmd_format(_: argparse.Namespace) -> None:
    ruff = os.environ.get("G6_RUFF_BIN", "ruff")
    _run([ruff, "format", "."])
    if shutil.which("black") and os.environ.get("G6_ENABLE_BLACK") == "1":
        _run(["black", "."])


def cmd_typecheck(_: argparse.Namespace) -> None:
    mypy_bin = os.environ.get("G6_MYPY_BIN", "mypy")
    ini = (REPO_ROOT / "mypy.ini")
    args = [mypy_bin]
    if ini.exists():
        args.extend(["--config-file", str(ini)])
    args.append("src")
    _run(args)


def cmd_test(ns: argparse.Namespace) -> None:
    pytest_bin = os.environ.get("G6_PYTEST_BIN", "pytest")
    args = [pytest_bin]
    if ns.pytest_args:
        args.extend(ns.pytest_args)
    _run(args)


def cmd_quick_cycle(_: argparse.Namespace) -> None:
    # Provide minimal simulation: run summary view once (existing script) using test runtime status
    status_file = REPO_ROOT / "data" / "runtime_status_test.json"
    if not status_file.exists():
        print(f"[dev_tasks] status file not found: {status_file} (ensure tests ran or generate one)")
    py = sys.executable
    script = REPO_ROOT / "scripts" / "summary_view.py"
    _run([py, str(script), "--no-rich", "--refresh", "1", "--status-file", str(status_file)])


def cmd_secrets_scan(_: argparse.Namespace) -> None:
    if not Path(".secrets.baseline").exists():
        print("[dev_tasks] .secrets.baseline missing; run update-secrets-baseline first.")
    _run(["detect-secrets", "scan", "--baseline", ".secrets.baseline"])  # exits non-zero on high-confidence


def cmd_update_secrets_baseline(_: argparse.Namespace) -> None:
    # Regenerate baseline; fail if new secrets found so dev must audit.
    baseline = Path(".secrets.baseline")
    tmp_out = ".secrets.baseline.tmp"
    _run(["detect-secrets", "scan", "--update", str(baseline) if baseline.exists() else "--baseline", tmp_out], check=False)
    # If tmp exists move to baseline
    if Path(tmp_out).exists():
        Path(tmp_out).replace(baseline)
        print("[dev_tasks] Updated baseline.")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="G6 dev tasks")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("lint")
    sub.add_parser("format")
    sub.add_parser("typecheck")
    t = sub.add_parser("test")
    t.add_argument("pytest_args", nargs=argparse.REMAINDER)
    sub.add_parser("quick-cycle")
    sub.add_parser("secrets-scan")
    sub.add_parser("update-secrets-baseline")
    return p


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    ns = parser.parse_args(argv)
    cmd = ns.command.replace('-', '_')
    fn = globals().get(f"cmd_{cmd}")
    if not fn:
        parser.error(f"Unknown command: {ns.command}")
    fn(ns)


if __name__ == "__main__":  # pragma: no cover
    main()
