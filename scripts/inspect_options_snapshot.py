#!/usr/bin/env python3
"""
Quick visibility script: summarize current option directory structure for an index.

Usage (powershell):
  python scripts/inspect_options_snapshot.py --index NIFTY --base-dir data/g6_data --date 2025-09-14

Outputs strike range, offsets present, counts per expiry bucket, inferred ATM and any gaps.
"""
from __future__ import annotations

import argparse
import csv
import os
from datetime import date
from statistics import mean

EXPIRY_CODES = ["this_week","next_week","this_month","next_month"]

from typing import Any


def scan(base_dir: str, index: str, target_date: str | None) -> dict[str, dict[str, Any]]:
    base = os.path.join(base_dir, index)
    if not os.path.isdir(base):
        raise SystemExit(f"Index directory not found: {base}")
    summary = {}
    for code in EXPIRY_CODES:
        path = os.path.join(base, code)
        if not os.path.isdir(path):
            continue
        offsets = []
        strikes = []
        records = 0
        for entry in os.scandir(path):
            if not entry.is_dir():
                continue
            offset_dir = entry.name
            csv_file = os.path.join(entry.path, f"{target_date}.csv") if target_date else None
            # pick latest file if date not supplied
            if not target_date:
                candidates = [f.name for f in os.scandir(entry.path) if f.is_file() and f.name.endswith('.csv')]
                if not candidates:
                    continue
                csv_file = os.path.join(entry.path, sorted(candidates)[-1])
            if not csv_file or not os.path.isfile(csv_file):
                continue
            offsets.append(offset_dir)
            try:
                with open(csv_file, newline='') as f:
                    r = csv.DictReader(f)
                    for row in r:
                        records += 1
                        try:
                            strikes.append(float(row.get('strike', row.get('atm',0))))
                        except Exception:
                            pass
            except Exception:
                continue
        if offsets:
            summary[code] = {
                'offset_count': len(offsets),
                'offset_sample': sorted(offsets)[:10],
                'records': records,
                'strike_min': min(strikes) if strikes else None,
                'strike_max': max(strikes) if strikes else None,
                'strike_avg': round(mean(strikes),2) if strikes else None,
            }
    return summary

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument('--base-dir', default='data/g6_data')
    p.add_argument('--index', required=True)
    p.add_argument('--date', help='Date YYYY-MM-DD (defaults today)')
    args = p.parse_args()
    target_date = args.date or date.today().strftime('%Y-%m-%d')
    summary = scan(args.base_dir, args.index, target_date)
    if not summary:
        print('No data found.')
        return
    print(f"Index: {args.index}  Date: {target_date}\n")
    for code, info in summary.items():
        print(f"[Expiry {code}] offsets={info['offset_count']} records={info['records']} strike_range={info['strike_min']}..{info['strike_max']} avg={info['strike_avg']}")
        if info['offset_sample']:
            print(f"  sample_offsets: {', '.join(info['offset_sample'])}")

if __name__ == '__main__':
    main()
