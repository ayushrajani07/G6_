#!/usr/bin/env python3
"""CSV Backfill / Placeholder Generator

Purpose:
  For a target ISO date, create empty placeholder CSV files in any bucket directories
  that have historical data (>=1 other date file) but are missing the target file.
  This is useful to:
    - Stabilize analytics that assume a uniform lattice of strikes per day
    - Allow the audit tool to distinguish between truly missing vs intentionally skipped

Behavior:
  - Scans under base root (default data/g6_data) for index/expiry_tag/bucket dirs.
  - If bucket contains at least one CSV for a different date and not the target date,
    writes an empty file with header only (unless --no-header specified).
  - Skips buckets with zero CSV files (no expectation yet).
  - Skips indices whose configured expiries (in config/g6_config.json) do not include the tag
    unless --ignore-config is passed (prevents accidental creation outside allowed scope).
  - Supports dry-run mode to preview actions.

Environment:
  G6_CSV_BASE_DIR to override root when --root not supplied.

Exit codes:
  0 success (even if nothing to do)
  1 unexpected exception

"""
from __future__ import annotations
import os, sys, json, argparse, datetime as dt
from pathlib import Path
from typing import List, Dict

KNOWN_TAGS = {"this_week","this_month","next_week","next_month"}


def load_config_indices(root: Path) -> Dict[str, Dict[str, object]]:
    cfg_path = root.parent.parent / 'config' / 'g6_config.json'
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
        return (cfg.get('indices') or {})  # type: ignore
    except Exception:
        return {}


def discover_buckets(tag_dir: Path):
    for p in tag_dir.iterdir():
        if p.is_dir():
            name = p.name
            if name.startswith(('+','-')):
                if name[1:].isdigit():
                    yield p
            elif name.isdigit():
                yield p


def ensure_header(path: Path, header: str, no_header: bool):
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        if not no_header:
            f.write(header + '\n')


def backfill(root: Path, date_str: str, *, dry_run: bool, no_header: bool, ignore_config: bool, header: str) -> Dict[str, List[str]]:
    actions: Dict[str, List[str]] = {}
    indices_cfg = load_config_indices(root) if not ignore_config else {}
    for index_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        index_name = index_dir.name
        allowed_tags = set(indices_cfg.get(index_name, {}).get('expiries') or []) if indices_cfg else None
        for tag_dir in sorted(p for p in index_dir.iterdir() if p.is_dir() and p.name in KNOWN_TAGS):
            tag_name = tag_dir.name
            if allowed_tags is not None and tag_name not in allowed_tags:
                continue  # config disallows
            for bucket_dir in discover_buckets(tag_dir):
                csvs = [f for f in bucket_dir.glob('*.csv') if f.is_file()]
                if not csvs:
                    continue  # no expectation yet
                have_target = any(f.stem == date_str or f.name.startswith(date_str + '.') for f in csvs)
                if have_target:
                    continue
                # Need to create placeholder
                rel = str(bucket_dir.relative_to(root))
                actions.setdefault(index_name, []).append(f"{rel}/{date_str}.csv")
                if not dry_run:
                    ensure_header(bucket_dir / f"{date_str}.csv", header=header, no_header=no_header)
    return actions


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description="Backfill missing per-bucket CSV placeholders for a date")
    ap.add_argument('--date', default=None, help='Target ISO date (default today)')
    ap.add_argument('--root', default=None, help='Root CSV dir (default env G6_CSV_BASE_DIR or data/g6_data)')
    ap.add_argument('--dry-run', action='store_true', help='List files that would be created without writing')
    ap.add_argument('--no-header', action='store_true', help='Create empty file without header row')
    ap.add_argument('--ignore-config', action='store_true', help='Ignore configured expiries gating (create wherever lattice exists)')
    ap.add_argument('--header', default='timestamp,offset,index_price,atm_strike,call_iv,put_iv,call_oi,put_oi,call_ltp,put_ltp,call_volume,put_volume,pcr', help='Header line for new placeholder files')
    ap.add_argument('--pretty', action='store_true', help='Pretty print JSON result')
    args = ap.parse_args(argv)

    date_str = args.date or dt.date.today().isoformat()
    root = Path(args.root or os.environ.get('G6_CSV_BASE_DIR') or 'data/g6_data')

    try:
        actions = backfill(root, date_str, dry_run=args.dry_run, no_header=args.no_header, ignore_config=args.ignore_config, header=args.header)
        out = {"root": str(root), "date": date_str, "created": actions, "dry_run": args.dry_run}
        if args.pretty:
            print(json.dumps(out, indent=2))
        else:
            print(json.dumps(out, separators=(',',':')))
        return 0
    except Exception as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
