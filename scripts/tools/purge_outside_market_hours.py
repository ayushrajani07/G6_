#!/usr/bin/env python3
"""
Purge rows outside market hours from CSV files in a directory tree.

- Uses src.utils.timeutils.get_market_session_bounds(trade_date) to get
  inclusive [open, close] for each file's date (derived from filename stem YYYY-MM-DD).
- If a file has timestamps with date/time (e.g., YYYY-MM-DDTHH:MM:SS or 'YYYY-MM-DD HH:MM:SS'),
  only the time portion is used for filtering. If only HH:MM:SS is present, the file date drives the bounds.
- Keeps header; writes back atomically (temp + replace). Skips files already compliant.

CLI:
  python scripts/tools/purge_outside_market_hours.py --root data/g6_data [--open HH:MM:SS --close HH:MM:SS]

Notes:
- Files whose stem is not parseable as YYYY-MM-DD are processed using today's bounds.
- Rows with unparsable timestamps are dropped (strict policy to guarantee compliance).
"""
from __future__ import annotations

import argparse
import csv
import os
from collections.abc import Iterable
from datetime import date
from pathlib import Path

# Lazy import to avoid path headaches when tool is called as a script
try:
    from src.utils.timeutils import get_market_session_bounds  # type: ignore
except Exception:
    get_market_session_bounds = None  # type: ignore


def _parse_time_key(ts: str) -> str:
    ts = (ts or "").strip()
    if not ts:
        return ""
    if "T" in ts:
        try:
            return ts.split("T", 1)[1][:8]
        except Exception:
            return ""
    if " " in ts:
        try:
            return ts.split(" ", 1)[1][:8]
        except Exception:
            return ""
    return ts[:8]


def _hhmmss_to_seconds(hms: str) -> int:
    try:
        h, m, s = (int(x) for x in hms.split(":", 2))
        return h * 3600 + m * 60 + s
    except Exception:
        return -1


def purged_rows(in_path: Path, open_hms: str, close_hms: str) -> tuple[list[dict], int, int]:
    """Return (kept_rows, removed_count, total_rows). Drops rows with bad timestamps or outside [open, close]."""
    kept: list[dict] = []
    removed = 0
    total = 0
    o = _hhmmss_to_seconds(open_hms)
    c = _hhmmss_to_seconds(close_hms)
    if o < 0 or c < 0 or o >= c:
        raise ValueError(f"Invalid window {open_hms} .. {close_hms}")
    with open(in_path, newline="") as f:
        r = csv.DictReader(f)
        fieldnames = r.fieldnames or []
        for row in r:
            total += 1
            tkey = _parse_time_key(row.get("timestamp", ""))
            if not tkey:
                removed += 1
                continue
            t = _hhmmss_to_seconds(tkey)
            if t < 0:
                removed += 1
                continue
            if t < o or t > c:
                removed += 1
                continue
            kept.append({k: row.get(k, "") for k in fieldnames})
    return kept, removed, total


def write_atomic(out_path: Path, fieldnames: Iterable[str], rows: Iterable[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(fieldnames))
        w.writeheader()
        w.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)


def get_bounds_for_file(p: Path, override_open: str | None, override_close: str | None) -> tuple[str, str]:
    if override_open and override_close:
        return override_open, override_close
    # Resolve from helper per file date; fallback to defaults if helper missing
    try:
        d = date.fromisoformat(p.stem)
    except Exception:
        d = date.today()
    if get_market_session_bounds is not None:
        try:
            start_dt, end_dt = get_market_session_bounds(d)
            return start_dt.strftime("%H:%M:%S"), end_dt.strftime("%H:%M:%S")
        except Exception:
            pass
    return "09:15:30", "15:30:00"


def main() -> int:
    ap = argparse.ArgumentParser(description="Purge out-of-hours rows from CSVs under a root directory.")
    ap.add_argument("--root", required=True, help="Root directory to scan (recursive)")
    ap.add_argument("--open", dest="open_hms", help="Override inclusive market open HH:MM:SS")
    ap.add_argument("--close", dest="close_hms", help="Override inclusive market close HH:MM:SS")
    ap.add_argument("--dry-run", action="store_true", help="Scan and report only; do not modify files")
    args = ap.parse_args()

    root = Path(args.root)
    if not root.exists():
        print(f"[ERR] Root not found: {root}")
        return 2

    total_files = 0
    changed_files = 0
    total_removed = 0

    for p in root.rglob("*.csv"):
        if not p.is_file():
            continue
        total_files += 1
        o, c = get_bounds_for_file(p, args.open_hms, args.close_hms)
        kept, removed, total = purged_rows(p, o, c)
        if removed > 0:
            if not args.dry_run:
                # preserve original header order
                with open(p, newline="") as f:
                    fieldnames = csv.DictReader(f).fieldnames or []
                write_atomic(p, fieldnames, kept)
            changed_files += 1
            total_removed += removed

    print(f"[DONE] Scanned {total_files} file(s); modified {changed_files}; removed {total_removed} row(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
