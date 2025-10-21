#!/usr/bin/env python3
"""
Clean up CSVs under any g6_data directories by removing rows where
any of these fields are below a threshold (default 50000):
  - ce_vol
  - pe_vol
  - ce_oi
  - pe_oi

Usage examples:
  python -m scripts.cleanup.clean_g6_data_csvs --dry-run
  python -m scripts.cleanup.clean_g6_data_csvs --threshold 75000
  python -m scripts.cleanup.clean_g6_data_csvs --verify-only

Notes:
- Only CSVs located under folders whose path includes "g6_data" are processed.
- Files missing any of the required columns are skipped with a warning.
- Processing is chunked to reduce memory usage; files are rewritten only if rows are dropped.
"""
from __future__ import annotations

import argparse
import os
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import pandas as pd

REQUIRED_COLS = ["ce_vol", "pe_vol", "ce_oi", "pe_oi"]


@dataclass
class FileResult:
    path: str
    rows_before: int
    rows_after: int
    dropped: int
    skipped_missing_cols: bool = False
    error: str | None = None

    @property
    def changed(self) -> bool:
        return self.rows_after != self.rows_before and not self.skipped_missing_cols and self.error is None


def find_g6_data_csvs(root: str) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        # Restrict to any path that includes 'g6_data'
        if "g6_data" not in dirpath.replace("/", os.sep).split(os.sep):
            # Quick check: allow nested matching as well
            if "g6_data" not in dirpath:
                continue
        for fn in filenames:
            if fn.lower().endswith(".csv"):
                yield os.path.join(dirpath, fn)


def _coerce_numeric(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    # Treat NaNs as 0 (thus will be dropped if threshold > 0)
    return s.fillna(0)


def _iter_csv_chunks(path: str, chunksize: int) -> Iterator[pd.DataFrame]:
    """Yield DataFrame chunks with robust parsing (encoding and bad-line handling)."""
    last_err: Exception | None = None
    # Attempt 1: utf-8 + C engine
    try:
        for chunk in pd.read_csv(path, chunksize=chunksize, encoding="utf-8", engine="c", on_bad_lines="skip", dtype="object"):
            yield chunk
        return
    except Exception as e:
        last_err = e
    # Attempt 2: utf-8-sig + C engine
    try:
        for chunk in pd.read_csv(path, chunksize=chunksize, encoding="utf-8-sig", engine="c", on_bad_lines="skip", dtype="object"):
            yield chunk
        return
    except Exception as e:
        last_err = e
    # Attempt 3: latin-1 + python engine
    try:
        for chunk in pd.read_csv(path, chunksize=chunksize, encoding="latin-1", engine="python", on_bad_lines="skip", dtype="object"):
            yield chunk
        return
    except Exception as e:
        last_err = e
    # If we got here, all attempts failed
    raise last_err if last_err is not None else RuntimeError("read_csv failed")


def _read_head(path: str) -> pd.DataFrame:
    last_err: Exception | None = None
    try:
        return pd.read_csv(path, nrows=1, encoding="utf-8", engine="c", on_bad_lines="skip", dtype="object")
    except Exception as e:
        last_err = e
    try:
        return pd.read_csv(path, nrows=1, encoding="utf-8-sig", engine="c", on_bad_lines="skip", dtype="object")
    except Exception as e:
        last_err = e
    try:
        return pd.read_csv(path, nrows=1, encoding="latin-1", engine="python", on_bad_lines="skip", dtype="object")
    except Exception as e:
        last_err = e
    raise last_err if last_err is not None else RuntimeError("read_csv head failed")


def process_file(path: str, threshold: int, dry_run: bool, verify_only: bool, chunksize: int = 200_000) -> FileResult:
    rows_before = 0
    rows_after = 0

    # Check columns first from a small sample to decide if we should proceed
    try:
        head = _read_head(path)
    except Exception as e:
        return FileResult(path, 0, 0, 0, error=f"read error: {e}")

    missing = [c for c in REQUIRED_COLS if c not in head.columns]
    if missing:
        return FileResult(path, 0, 0, 0, skipped_missing_cols=True)

    if verify_only:
        try:
            violations = 0
            for chunk in _iter_csv_chunks(path, chunksize=chunksize):
                rows_before += len(chunk)
                ce_vol = _coerce_numeric(chunk["ce_vol"]) < threshold
                pe_vol = _coerce_numeric(chunk["pe_vol"]) < threshold
                ce_oi = _coerce_numeric(chunk["ce_oi"]) < threshold
                pe_oi = _coerce_numeric(chunk["pe_oi"]) < threshold
                bad = ce_vol | pe_vol | ce_oi | pe_oi
                violations += int(bad.sum())
                rows_after += len(chunk) - int(bad.sum())
            dropped = rows_before - rows_after
            # In verify-only mode, we don't change files; report counts
            return FileResult(path, rows_before, rows_after, dropped)
        except Exception as e:
            return FileResult(path, 0, 0, 0, error=f"verify error: {e}")

    # Cleaning mode (dry-run supported)
    tmp_fd = None
    tmp_path = None
    try:
        if not dry_run:
            # Create temp file in same directory for safe overwrite
            d = os.path.dirname(path)
            os.makedirs(d, exist_ok=True)
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=".clean_", suffix=".csv", dir=d)
            os.close(tmp_fd)
            tmp_fd = None

        first_write = True
        dropped_total = 0
        for chunk in _iter_csv_chunks(path, chunksize=chunksize):
            rows_before += len(chunk)
            # Compute mask to keep rows
            ce_vol = _coerce_numeric(chunk["ce_vol"]) >= threshold
            pe_vol = _coerce_numeric(chunk["pe_vol"]) >= threshold
            ce_oi = _coerce_numeric(chunk["ce_oi"]) >= threshold
            pe_oi = _coerce_numeric(chunk["pe_oi"]) >= threshold
            keep = ce_vol & pe_vol & ce_oi & pe_oi
            kept_chunk = chunk.loc[keep]
            rows_after += len(kept_chunk)
            dropped_total += int((~keep).sum())

            if not dry_run:
                kept_chunk.to_csv(
                    tmp_path,
                    index=False,
                    mode="w" if first_write else "a",
                    header=first_write,
                )
                first_write = False

        # If not dry-run and there were changes, replace original
        if not dry_run and tmp_path is not None:
            if rows_after == rows_before:
                # No changes; remove temp file
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            else:
                # Atomic-ish replace
                os.replace(tmp_path, path)

        return FileResult(path, rows_before, rows_after, rows_before - rows_after)
    except Exception as e:
        # Cleanup temp on error
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return FileResult(path, rows_before, rows_after, rows_before - rows_after, error=str(e))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Clean g6_data CSVs by dropping rows below threshold for vol/oi fields.")
    p.add_argument("--root", default=".", help="Root folder to search (default: current directory)")
    p.add_argument("--threshold", type=int, default=50000, help="Minimum required value for ce_vol, pe_vol, ce_oi, pe_oi (default: 50000)")
    p.add_argument("--dry-run", action="store_true", help="Compute and report changes without modifying files")
    p.add_argument("--verify-only", action="store_true", help="Scan and report potential drops, without any write")
    p.add_argument("--limit", type=int, default=0, help="Limit number of files to process (0 = no limit)")

    args = p.parse_args(argv)

    files = list(find_g6_data_csvs(args.root))
    if args.limit > 0:
        files = files[: args.limit]

    total = len(files)
    changed = 0
    skipped = 0
    errors = 0
    rows_before_sum = 0
    rows_after_sum = 0
    dropped_sum = 0

    print(f"Scanning {total} CSV file(s) under '{args.root}' with threshold={args.threshold}...")
    for i, path in enumerate(files, 1):
        res = process_file(path, args.threshold, args.dry_run, args.verify_only)
        rows_before_sum += res.rows_before
        rows_after_sum += res.rows_after
        dropped_sum += res.dropped

        if res.error:
            errors += 1
            print(f"[ERROR] {path}: {res.error}")
        elif res.skipped_missing_cols:
            skipped += 1
            print(f"[SKIP ] {path}: missing required columns {REQUIRED_COLS}")
        else:
            if res.changed:
                changed += 1
                print(f"[CHG  ] {path}: -{res.dropped} rows (from {res.rows_before} to {res.rows_after})")
            else:
                print(f"[OK   ] {path}: no changes")

        if i % 50 == 0:
            print(f"...processed {i}/{total}")

    print("\nSummary")
    print("-------")
    mode = "VERIFY" if args.verify_only else ("DRY-RUN" if args.dry_run else "APPLY")
    print(f"Mode: {mode}")
    print(f"Files scanned: {total}")
    print(f"Changed     : {changed}")
    print(f"Skipped     : {skipped}")
    print(f"Errors      : {errors}")
    print(f"Rows before : {rows_before_sum}")
    print(f"Rows after  : {rows_after_sum}")
    print(f"Rows dropped: {dropped_sum}")

    # Non-zero exit if errors occurred
    return 1 if errors > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
