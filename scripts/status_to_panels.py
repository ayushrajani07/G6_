from __future__ import annotations

"""TOMBSTONED: legacy panels bridge (status_to_panels.py).

All historical implementation has been removed. The unified summary path
(`python -m scripts.summary.app`) is the supported interface.

Runtime behavior:
  * If G6_EGRESS_FROZEN=1 -> exit 0 (feature set frozen / intentionally inert)
  * Else -> print deprecation notice (unless suppressed) and exit 2.

Environment flags:
  G6_EGRESS_FROZEN       When truthy, silently succeeds (optional one-line note).
  G6_SUPPRESS_LEGACY_CLI When truthy, suppresses all output from this stub.

This tombstone remains only so any lingering automation invoking the old
script does not crash the process or produce stack traces.
"""
import os
import sys

_TRUTHY = {"1","true","yes","on"}

def _is_set(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in _TRUTHY

def main() -> int:  # pragma: no cover - trivial stub
    frozen = _is_set("G6_EGRESS_FROZEN")
    suppress = _is_set("G6_SUPPRESS_LEGACY_CLI")
    if frozen:
        if not suppress:
            print("[EGRESS_FROZEN] status_to_panels stub executed (no work performed).", file=sys.stderr)
        return 0
    if not suppress:
        print("[REMOVED] status_to_panels.py -> use `python -m scripts.summary.app` (see DEPRECATIONS.md).", file=sys.stderr)
    return 2

if __name__ == '__main__':  # pragma: no cover
    sys.exit(main())
