#!/usr/bin/env python3
"""CI Gate: Fail if rolling parity below threshold or fatal ratio above limit.

Inputs:
  --parity-min (float) minimum acceptable rolling parity average
  --fatal-max  (float) maximum acceptable fatal ratio (fatal / (fatal+recoverable)) over recent window

Data Sources (best-effort heuristics):
  1. Environment JSON snapshot path (if provided via G6_PARITY_SNAPSHOT_JSON)
     Expected keys: {"rolling_parity_avg": float, "fatal_count": int, "recoverable_count": int}
  2. Metrics scrape (optional future enhancement) – not implemented yet to avoid network coupling.

Exit Codes:
  0: Gate passed or data unavailable (soft pass) unless --strict-missing specified.
  1: Gate failed (threshold breach) or required data missing in strict mode.
"""
from __future__ import annotations

import argparse
import json
import os
from typing import Any


def load_snapshot() -> dict[str, Any]:
    path = os.getenv('G6_PARITY_SNAPSHOT_JSON')
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path,encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def compute_fatal_ratio(fatal: int | None, recoverable: int | None) -> float | None:
    if fatal is None and recoverable is None:
        return None
    f = int(fatal or 0)
    r = int(recoverable or 0)
    denom = f + r
    if denom <= 0:
        return 0.0
    return f / denom


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--parity-min', type=float, required=True)
    ap.add_argument('--fatal-max', type=float, required=True)
    ap.add_argument('--strict-missing', action='store_true', help='Fail if data missing')
    args = ap.parse_args()

    snap = load_snapshot()
    rolling = snap.get('rolling_parity_avg') if isinstance(snap, dict) else None
    fatal_count = snap.get('fatal_count') if isinstance(snap, dict) else None
    recoverable_count = snap.get('recoverable_count') if isinstance(snap, dict) else None
    fatal_ratio = compute_fatal_ratio(fatal_count, recoverable_count)

    problems: list[str] = []
    if rolling is not None:
        try:
            if float(rolling) < args.parity_min:
                problems.append(f"rolling_parity_avg {rolling} < min {args.parity_min}")
        except Exception:
            problems.append('invalid rolling parity value')
    else:
        if args.strict_missing:
            problems.append('missing rolling_parity_avg')

    if fatal_ratio is not None:
        if fatal_ratio > args.fatal_max:
            problems.append(f"fatal_ratio {fatal_ratio:.4f} > max {args.fatal_max}")
    else:
        if args.strict_missing:
            problems.append('missing fatal ratio inputs')

    if problems:
        print('GATE FAIL:')
        for p in problems:
            print(' -', p)
        return 1
    print('GATE PASS (parity/fatal thresholds met or data unavailable)')
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
