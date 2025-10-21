#!/usr/bin/env python
"""Integrity checker for detecting missing collection cycles.

Heuristic:
- Reads structured events log (default logs/events.log) expecting lines with JSON objects.
- Identifies cycle_start events, extracts cycle number (context.cycle).
- Detects gaps in ascending cycle sequence (e.g., saw 1,2,5 => missing 3,4 => 2 missing cycles).
- Emits summary to stdout and optionally increments Prometheus metric if metrics registry can be imported.

Usage:
  python scripts/check_integrity.py --events-file logs/events.log --metrics

Exit codes:
 0 = success, no gaps
 2 = gaps detected (still successful run)
 3 = fatal error reading file
"""
from __future__ import annotations

import argparse
import json
import sys


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Detect missing collection cycles from events log")
    p.add_argument('--events-file', default='logs/events.log', help='Path to structured events log')
    p.add_argument('--metrics', action='store_true', help='Increment g6_missing_cycles_total counter if available')
    p.add_argument('--max-lines', type=int, default=500_000, help='Safety cap on lines to read (default 500k)')
    return p.parse_args()


def load_cycles(path: str, max_lines: int) -> list[int]:
    cycles: list[int] = []
    try:
        with open(path, encoding='utf-8') as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get('event') == 'cycle_start':
                    ctx = obj.get('context') or {}
                    c = ctx.get('cycle')
                    if isinstance(c, int):
                        cycles.append(c)
    except FileNotFoundError:
        raise
    return cycles


def detect_gaps(cycles: list[int]) -> int:
    if not cycles:
        return 0
    cycles_sorted = sorted(set(cycles))
    missing = 0
    for prev, curr in zip(cycles_sorted, cycles_sorted[1:], strict=False):
        if curr > prev + 1:
            missing += (curr - prev - 1)
    return missing


def maybe_emit_metric(missing: int, enable: bool) -> bool:
    if missing <= 0 or not enable:
        return False
    try:
        from src.metrics import MetricsRegistry  # facade import
        # Initialize a throwaway registry (this will use global prometheus client registry)
        mr = MetricsRegistry()
        if hasattr(mr, 'missing_cycles'):
            mr.missing_cycles.inc(missing)  # type: ignore[attr-defined]
            return True
    except Exception:
        return False
    return False


def main() -> int:
    args = parse_args()
    try:
        cycles = load_cycles(args.events_file, args.max_lines)
    except FileNotFoundError:
        print(f"ERROR: events file not found: {args.events_file}", file=sys.stderr)
        return 3
    missing = detect_gaps(cycles)
    total = len(cycles)
    first = min(cycles) if cycles else None
    last = max(cycles) if cycles else None
    emitted = maybe_emit_metric(missing, args.metrics)
    status = 'OK' if missing == 0 else 'GAPS'
    print(json.dumps({
        'status': status,
        'cycles_observed': total,
        'first_cycle': first,
        'last_cycle': last,
        'missing_count': missing,
        'metric_emitted': emitted,
        'events_file': args.events_file
    }))
    if missing == 0:
        return 0
    return 2

if __name__ == '__main__':
    sys.exit(main())
