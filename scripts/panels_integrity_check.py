#!/usr/bin/env python
"""Panels Manifest Integrity Checker

(DEPRECATION NOTICE) This script will be consolidated into the unified CLI.
Prefer: `python scripts/g6.py integrity [--strict] [--json]`.
A one-time warning is emitted per process unless G6_SUPPRESS_LEGACY_CLI=1.

Usage:
  python scripts/panels_integrity_check.py [--panels-dir data/panels] [--strict] [--json] [--quiet]

Exit Codes:
  0 - Success (no issues)
  1 - Issues found (in strict mode or when --strict supplied)
  2 - Execution error (unexpected failure reading manifest or directory)

Behavior:
  Reads manifest.json, recomputes sha256 hashes of each panel's `data` section using
  canonical JSON (sort_keys, compact separators), and compares with the manifest `hashes` block.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_warned = False


def _maybe_warn() -> None:
    global _warned
    if _warned:
        return
    if os.getenv("G6_SUPPRESS_LEGACY_CLI", "").lower() in ("1", "true", "yes", "on"):
        return
    print(
        "[DEPRECATED] Use `g6 integrity` instead of panels_integrity_check.py (will be removed in a future release). Set G6_SUPPRESS_LEGACY_CLI=1 to silence.",
        file=sys.stderr,
    )
    _warned = True


# Ensure repo root (parent of scripts/) is on sys.path for `src` imports when executed directly.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.panels.validate import verify_manifest_hashes  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Verify panel manifest content hashes")
    p.add_argument(
        "--panels-dir",
        default="data/panels",
        help="Directory containing manifest.json and panel *_panel.json files",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero (1) if any issues are found",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON result to stdout",
    )
    p.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress human output when no issues (still prints JSON if --json)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _maybe_warn()
    args = parse_args(argv)
    panels_dir = Path(args.panels_dir)
    try:
        issues = verify_manifest_hashes(panels_dir)
    except Exception as e:  # noqa: BLE001
        if args.json:
            print(
                json.dumps({"error": f"unexpected_error:{e.__class__.__name__}"}),
                file=sys.stdout,
            )
        else:
            print(
                f"[panels-integrity] ERROR unexpected failure: {e.__class__.__name__}: {e}",
                file=sys.stderr,
            )
        return 2

    exit_code = 0
    if issues and args.strict:
        exit_code = 1

    if args.json:
        obj = {"issues": issues, "count": len(issues)}
        print(json.dumps(obj, indent=2 if not args.quiet else None))
    else:
        if issues:
            print(f"[panels-integrity] Issues detected ({len(issues)}):")
            for fname, problem in sorted(issues.items()):
                print(f"  - {fname}: {problem}")
        elif not args.quiet:
            print("[panels-integrity] OK (no issues)")

    return exit_code


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
