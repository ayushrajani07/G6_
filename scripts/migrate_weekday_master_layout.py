#!/usr/bin/env python3
"""migrate_weekday_master_layout.py

Convert weekday master layouts to final structure:
    Final:   data/weekday_master/<Weekday>/<INDEX>/<EXPIRY>/<OFFSET>.csv
    Legacy:  data/weekday_master/<Weekday>/<INDEX>_<EXPIRY>_<OFFSET>.csv
    Prior:   data/weekday_master/<INDEX>/<EXPIRY>/<OFFSET>/<Weekday>.csv

Usage (dry run by default):
  python scripts/migrate_weekday_master_layout.py --root data/weekday_master
To actually move files, pass --apply. Use --copy to copy instead of move.
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

WEEKDAYS = {"Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"}

def migrate(root: Path, apply: bool = False, copy: bool = False) -> int:
    moved = 0
    if not root.exists():
        print(f"[WARN] root {root} not found")
        return 0
    # 1) Legacy: <Weekday>/<INDEX>_<EXPIRY>_<OFFSET>.csv
    for day_dir in root.iterdir():
        if not day_dir.is_dir() or day_dir.name not in WEEKDAYS:
            continue
        weekday = day_dir.name
        for f in day_dir.glob("*.csv"):
            name = f.stem  # INDEX_EXPIRY_OFFSET
            parts = name.split("_")
            if len(parts) < 3:
                print(f"[SKIP] not a master file: {f.name}")
                continue
            index = parts[0]
            expiry = parts[1]
            offset = "_".join(parts[2:])  # offsets can contain underscores
            dst = root / weekday / index / expiry / f"{offset}.csv"
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists():
                print(f"[INFO] exists, skip: {dst}")
                continue
            print(f"[PLAN] {'COPY' if copy else 'MOVE'} {f} -> {dst}")
            if apply:
                if copy:
                    shutil.copy2(f, dst)
                else:
                    shutil.move(str(f), str(dst))
                moved += 1
    # 2) Prior: <INDEX>/<EXPIRY>/<OFFSET>/<Weekday>.csv -> Final
    for index_dir in root.iterdir():
        if not index_dir.is_dir() or index_dir.name in WEEKDAYS:
            continue
        for expiry_dir in index_dir.iterdir():
            if not expiry_dir.is_dir():
                continue
            for offset_dir in expiry_dir.iterdir():
                if not offset_dir.is_dir():
                    continue
                for f in offset_dir.glob("*.csv"):
                    weekday = f.stem
                    if weekday not in WEEKDAYS:
                        continue
                    dst = root / weekday / index_dir.name / expiry_dir.name / f"{offset_dir.name}.csv"
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if dst.exists():
                        continue
                    print(f"[PLAN] {'COPY' if copy else 'MOVE'} {f} -> {dst}")
                    if apply:
                        if copy:
                            shutil.copy2(f, dst)
                        else:
                            shutil.move(str(f), str(dst))
                        moved += 1
    return moved

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default='data/weekday_master')
    ap.add_argument('--apply', action='store_true', help='Perform the migration (otherwise dry-run)')
    ap.add_argument('--copy', action='store_true', help='Copy instead of move')
    args = ap.parse_args()
    count = migrate(Path(args.root), apply=args.apply, copy=args.copy)
    print(f"[DONE] {'migrated' if args.apply else 'planned'} {count} files")

if __name__ == '__main__':
    main()
