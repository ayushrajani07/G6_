"""Dry-run demonstration of rich diff hashing (no Rich console required).

Purpose:
  Simulate a sequence of synthetic status snapshots, compute per-panel hashes
  using `compute_panel_hashes`, and show which panels would be refreshed
  when `G6_SUMMARY_RICH_DIFF=1` is enabled.

This DOES NOT modify layout or require terminal capabilities—it's a pure
stdout explainer to validate hashing behavior and expected update sets.

Usage:
  python scripts/summary/demo_rich_diff.py --cycles 5 --mode basic

Modes:
  basic   - deterministic scripted mutations
  random  - random subset of panel-affecting mutations per cycle

Environment respected:
  G6_SUMMARY_RICH_DIFF (if not truthy, script will still run but note disabled flag)

Exit code 0 on success.
"""
from __future__ import annotations

import argparse
import os
import pathlib
import random
import sys
import time
from typing import Any

# Ensure project root (2 levels up from this file) is on sys.path when executed
# as a script (python scripts/summary/demo_rich_diff.py). Without this, running
# the file directly sets sys.path[0] to scripts/summary, which prevents
# importing the top-level 'scripts' package path for nested modules.
_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from scripts.summary.rich_diff import compute_panel_hashes

RNG = random.Random(42)

BASE_STATUS = {
    "app": {"version": "1.0.0"},
    "indices": ["NIFTY","BANKNIFTY"],
    "alerts": [],
    "analytics": {"vol": 11.2},
    "resources": {"cpu": 0.07, "mem": 120},
    "storage": {"lag": 3},
}

MUTATIONS_ORDERED = [
    ("indices", lambda s: s["indices"].append("FINNIFTY")),
    ("alerts", lambda s: s["alerts"].append({"id": 1, "sev": "warn"})),
    ("analytics", lambda s: s["analytics"].update({"vol": 11.5})),
    ("perfstore", lambda s: s["resources"].update({"cpu": round(s["resources"]["cpu"] + 0.05, 3)})),
    ("storage", lambda s: s["storage"].update({"lag": s["storage"]["lag"] + 1})),
    ("header", lambda s: s.setdefault("app", {}).update({"version": "1.0." + str(len(s.get("indices", [])))})),
]

RANDOM_MUTATORS = [m for m in MUTATIONS_ORDERED]


def clone_status() -> dict[str, Any]:
    import copy
    return copy.deepcopy(BASE_STATUS)


def compute_changes(prev: dict[str,str] | None, current: dict[str,str]) -> list[str]:
    if prev is None:
        return list(current.keys())
    return [k for k,v in current.items() if prev.get(k) != v]


def run_basic(cycles: int) -> None:
    status = clone_status()
    baseline_hashes = None
    for cycle in range(1, cycles+1):
        if cycle <= len(MUTATIONS_ORDERED):
            target, mut = MUTATIONS_ORDERED[cycle-1]
            mut(status)
            mutation_note = f"applied mutation: {target}"
        else:
            mutation_note = "no mutation"
        hashes = compute_panel_hashes(status)
        changed = compute_changes(baseline_hashes, hashes)
        print(f"Cycle {cycle}: {mutation_note}")
        if baseline_hashes is None:
            print("  first cycle -> full refresh (all panels)")
        print("  changed panels:", ", ".join(changed) if changed else "<none>")
        # emulate selective update baseline store
        if baseline_hashes is None:
            baseline_hashes = hashes
        else:
            for k in changed:
                baseline_hashes[k] = hashes[k]
        time.sleep(0.05)


def run_random(cycles: int) -> None:
    status = clone_status()
    baseline_hashes = None
    for cycle in range(1, cycles+1):
        # choose 0-2 random mutations
        muts = RNG.sample(RANDOM_MUTATORS, RNG.randint(0,2))
        applied = []
        for name, fn in muts:
            fn(status)
            applied.append(name)
        hashes = compute_panel_hashes(status)
        changed = compute_changes(baseline_hashes, hashes)
        print(f"Cycle {cycle}: mutations={applied if applied else 'none'}")
        if baseline_hashes is None:
            print("  first cycle -> full refresh (all panels)")
        print("  changed panels:", ", ".join(changed) if changed else "<none>")
        if baseline_hashes is None:
            baseline_hashes = hashes
        else:
            for k in changed:
                baseline_hashes[k] = hashes[k]
        time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser(description="Rich diff hashing dry-run demo")
    ap.add_argument("--cycles", type=int, default=8)
    ap.add_argument("--mode", choices=["basic","random"], default="basic")
    args = ap.parse_args()
    enabled = os.getenv("G6_SUMMARY_RICH_DIFF", "0").lower() in {"1","true","yes","on"}
    print(f"[demo] G6_SUMMARY_RICH_DIFF={'on' if enabled else 'off'} (demo runs regardless)")
    if args.mode == "basic":
        run_basic(args.cycles)
    else:
        run_random(args.cycles)
    print("Done.")
    return 0

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
