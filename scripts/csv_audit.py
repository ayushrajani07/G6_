#!/usr/bin/env python3
"""CSV Audit Tool

Scans the active CSV storage root (default data/g6_data) and reports, for a given
ISO date (default today), which (index, logical_expiry_tag, moneyness_bucket)
files exist and which are missing relative to discovered buckets for that tag.

Heuristic rules:
- We treat any subdirectory of an index whose name matches one of known logical tags
  (this_week, this_month, next_week, next_month) as a logical expiry scope.
- Under each logical tag, subdirectories whose names parse as signed/unsigned strike
  offsets (e.g. 0, +50, -200) define the observed moneyness buckets.
- For the audit, "expected" means: if a bucket contains at least one other date's
  CSV file, then we expect a file for the target date.
- A bucket is marked:
    present: CSV for target date found
    missing: bucket has historical CSV(s) but not for target date
    empty:   bucket has no CSV files at all (no expectation yet)

JSON output structure:
{
  "root": "data/g6_data",
  "date": "2025-10-01",
  "indices": {
     "NIFTY": {
        "this_week": { "present": [...], "missing": [...], "empty": [...] },
        "this_month": { ... }
     },
     ...
  }
}

Environment overrides:
- G6_CSV_BASE_DIR sets root (falls back to config or default).

Exit code is 0 unless an unexpected exception occurs.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path
from typing import TypedDict

KNOWN_TAGS = {"this_week","this_month","next_week","next_month"}


def _load_config_expiries(project_root: Path) -> dict[str, set[str]]:
    """Load configured logical expiries per index from config/g6_config.json.

    Returns mapping INDEX -> set(tags). Missing file or parse errors yield empty mapping.
    """
    cfg_path = project_root / 'config' / 'g6_config.json'
    try:
        with open(cfg_path, encoding='utf-8') as f:
            raw = json.load(f)
        out: dict[str, set[str]] = {}
        for k, v in (raw.get('indices') or {}).items():  # type: ignore
            tags = v.get('expiries') or []  # type: ignore
            if isinstance(tags, list):
                out[k.upper()] = {str(t) for t in tags}
        return out
    except Exception:
        return {}


def discover_buckets(tag_dir: Path) -> list[Path]:
    buckets: list[Path] = []
    for p in tag_dir.iterdir():
        if not p.is_dir():
            continue
        name = p.name
        # Accept patterns: 0, +50, -50, 100, -1000 etc.
        if name.startswith(('+','-')):
            trimmed = name[1:]
            if trimmed.isdigit():
                buckets.append(p)
        elif name.isdigit():
            buckets.append(p)
    return sorted(buckets, key=lambda x: x.name)


def filter_bucket(name: str, *, max_steps: int | None, step_size: int) -> bool:
    """Return True if bucket should be included under max step constraints.

    name examples: '0', '+50', '-150'. We map to step index relative to ATM (0) by dividing
    absolute numeric value by step_size and comparing to max_steps.
    If max_steps is None, always include.
    Buckets whose absolute value is not an exact multiple of step_size are still kept (defensive),
    but can be excluded if they exceed range.
    """
    if max_steps is None:
        return True
    try:
        if name.startswith(('+','-')):
            v = int(name)
        else:
            v = int(name)
    except ValueError:
        return True  # non-numeric style; keep
    steps = abs(v) / step_size if step_size > 0 else abs(v)
    return steps <= max_steps + 1e-9


class TagReport(TypedDict):
    present: list[str]
    missing: list[str]
    empty: list[str]
    meta: dict[str, object]


def audit(root: Path, target_date: str, *, max_steps: int | None, step_size: int, per_index: dict[str, int]) -> dict[str, object]:
    result: dict[str, object] = {"root": str(root), "date": target_date, "indices": {}}
    if not root.exists():
        return result
    # Attempt to derive project root (two levels up from data/g6_data or parent of root)
    project_root = Path(os.path.abspath(os.path.join(root, '..', '..')))
    cfg_expiries = _load_config_expiries(project_root)
    for index_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        index_name = index_dir.name
        idx_max_steps = per_index.get(index_name.upper(), max_steps)
        idx_obj: dict[str, TagReport] = {}
        configured = cfg_expiries.get(index_name.upper())
        physical_tags = {p.name for p in index_dir.iterdir() if p.is_dir() and p.name in KNOWN_TAGS}
        for tag_dir in sorted(p for p in index_dir.iterdir() if p.is_dir() and p.name in KNOWN_TAGS):
            tag_name = tag_dir.name
            tag_report: TagReport = {"present": [], "missing": [], "empty": [], "meta": {}}
            for bucket_dir in discover_buckets(tag_dir):
                if not filter_bucket(bucket_dir.name, max_steps=idx_max_steps, step_size=step_size):
                    continue
                csvs = [f for f in bucket_dir.glob('*.csv') if f.is_file()]
                if not csvs:
                    tag_report["empty"].append(bucket_dir.name)
                    continue
                # Determine if target-date CSV exists (allow .vN suffix variations before .csv if any)
                present = any(f.stem == target_date or f.name.startswith(target_date + '.') for f in csvs)
                if present:
                    tag_report["present"].append(bucket_dir.name)
                else:
                    tag_report["missing"].append(bucket_dir.name)
            # Attach tag-level meta hints (only once per tag)
            try:  # best-effort
                meta: dict[str, object] = {}
                if configured is not None:
                    meta['configured_for_index'] = tag_name in configured
                if configured and tag_name not in configured:
                    meta['reason'] = 'tag_not_in_config'
                elif configured and tag_report['missing']:
                    meta['reason'] = 'expected_by_config'  # configured but some buckets missing
                elif not configured and tag_report['missing']:
                    meta['reason'] = 'no_config_but_historic'  # no explicit config; historic buckets define expectation
                # If tag absent physically but configured, represent as synthetic entry
                absent_tags = (configured - physical_tags) if configured else set()
                tag_report['meta'] = meta
                # Add synthetic empty record for absent configured tags
                for absent in sorted(absent_tags):
                    if absent not in idx_obj:
                        idx_obj[absent] = {"present": [], "missing": [], "empty": [], "meta": {"configured_for_index": True, "reason": "configured_tag_missing_dir"}}
            except Exception:
                pass
            idx_obj[tag_name] = tag_report
        if idx_obj:
            result["indices"][index_name] = idx_obj  # type: ignore[index]
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Audit CSV presence for a given date")
    ap.add_argument('--date', help='ISO date (YYYY-MM-DD); default today', default=None)
    ap.add_argument('--root', help='CSV root override; defaults to G6_CSV_BASE_DIR or data/g6_data', default=None)
    ap.add_argument('--pretty', action='store_true', help='Pretty-print JSON')
    ap.add_argument('--max-steps', type=int, default=None, help='Limit to ±N steps from ATM (step units defined by --step-size).')
    ap.add_argument('--step-size', type=int, default=50, help='Numeric increment representing one step (default 50).')
    ap.add_argument('--index-max-steps', action='append', default=[], metavar='IDX=N',
                    help='Override max steps for specific index (e.g. --index-max-steps BANKNIFTY=12). Can be repeated.')
    args = ap.parse_args(argv)

    date_str = args.date or dt.date.today().isoformat()
    root = Path(args.root or os.environ.get('G6_CSV_BASE_DIR') or 'data/g6_data')

    per_index: dict[str, int] = {}
    for item in args.index_max_steps:
        if '=' in item:
            k,v = item.split('=',1)
            k = k.strip().upper()
            try:
                per_index[k] = int(v)
            except ValueError:
                pass
    report = audit(root, date_str, max_steps=args.max_steps, step_size=args.step_size, per_index=per_index)
    if args.pretty:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(json.dumps(report, separators=(',',':')))
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
