#!/usr/bin/env python3
"""
Sanitize existing option CSV files by removing rows whose expiry_date column is invalid.

Two validation strategies:
 1. Dominant mode (default): keep only the most frequent expiry_date value found in each file.
 2. Whitelist mode: keep only expiry_date values present in a provided allowed set (via --allowed or provider lookup).

Features:
 - Recursive scan of option data directory structure (index/expiry_tag/offset_dir/date.csv).
 - Dry-run support (reports what would change without writing).
 - Backup originals (*.bak) before in-place replacement (unless --no-backup).
 - Summary statistics at end.
 - Optional provider-based whitelist (requires live provider environment) via --use-provider.

Usage examples:
  python scripts/sanitize_csv_expiries.py --base-dir data/g6_data --indices NIFTY,BANKNIFTY --dry-run
  python scripts/sanitize_csv_expiries.py --base-dir data/g6_data --indices NIFTY --allowed 2025-09-25,2025-10-02
  python scripts/sanitize_csv_expiries.py --use-provider --indices NIFTY,BANKNIFTY

Exit codes:
  0 success (even if no changes needed)
  1 error during processing
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
from collections import Counter, defaultdict

LOG = logging.getLogger("sanitize_csv_expiries")

DEFAULT_INDICES = ["NIFTY","BANKNIFTY","FINNIFTY","SENSEX","MIDCPNIFTY"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sanitize option CSV expiry_date column")
    p.add_argument("--base-dir", default="data/g6_data", help="Root options data directory (as used by CsvSink)")
    p.add_argument("--indices", help="Comma separated list of indices to process; defaults to common indices", default=None)
    p.add_argument("--allowed", help="Comma separated list of allowed expiry dates (YYYY-MM-DD). If provided, whitelist mode.")
    p.add_argument("--use-provider", action="store_true", help="Fetch allowed expiry dates from provider (overrides --allowed if both)")
    p.add_argument("--dominant", action="store_true", help="Force dominant mode even if --allowed provided (for testing)")
    p.add_argument("--dry-run", action="store_true", help="Do not modify files; just report changes")
    p.add_argument("--no-backup", action="store_true", help="Do not create .bak backup files when modifying")
    p.add_argument("--min-rows", type=int, default=2, help="Skip files with fewer than this many data rows (excluding header)")
    p.add_argument("--verbose", action="store_true", help="Verbose logging")
    return p.parse_args()


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format='[%(levelname)s] %(message)s')


def load_provider_allowed(index: str) -> list[str]:
    """Attempt to load allowed expiry dates via provider facade.
    Returns empty list on failure (script will fallback to dominant mode for that index).
    """
    try:
        from src.providers import providers  # type: ignore
        dates = providers.get_expiry_dates(index)
        # Normalize to YYYY-MM-DD strings
        return sorted({d.strftime('%Y-%m-%d') for d in dates})
    except Exception as e:  # pragma: no cover - environment dependent
        LOG.warning("Provider expiry lookup failed for %s: %s", index, e)
        return []


def discover_option_files(base_dir: str, index: str) -> list[str]:
    """Collect leaf CSV file paths for an index respecting expected directory layout."""
    collected: list[str] = []
    root = os.path.join(base_dir, index)
    if not os.path.isdir(root):
        return collected
    # Layout: base_dir/index/expiry_tag/offset_dir/date.csv
    for expiry_tag in os.listdir(root):
        tag_path = os.path.join(root, expiry_tag)
        if not os.path.isdir(tag_path):
            continue
        for offset_dir in os.listdir(tag_path):
            off_path = os.path.join(tag_path, offset_dir)
            if not os.path.isdir(off_path):
                continue
            for fn in os.listdir(off_path):
                if not fn.endswith('.csv'):
                    continue
                collected.append(os.path.join(off_path, fn))
    return collected


def analyze_file(path: str) -> tuple[list[list[str]], list[str], Counter]:
    with open(path, newline='') as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return [], [], Counter()
        rows = [r for r in reader]
    # Identify column index of expiry_date
    try:
        exp_idx = header.index('expiry_date')
    except ValueError:
        return rows, header, Counter()  # no expiry_date column
    freq: Counter = Counter()
    for r in rows:
        if len(r) > exp_idx:
            freq[r[exp_idx]] += 1
    return rows, header, freq


def write_sanitized(path: str, header: list[str], rows: list[list[str]], kept_indices: list[int], dry_run: bool, no_backup: bool) -> None:
    if dry_run:
        return
    if not no_backup and not os.path.exists(path + '.bak'):
        try:
            os.replace(path, path + '.bak')
        except Exception:
            # Fallback: copy then continue (avoid import shutil if not needed)
            try:
                import shutil
                shutil.copy2(path, path + '.bak')
            except Exception:
                pass
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        for idx in kept_indices:
            writer.writerow(rows[idx])
    os.replace(tmp_path, path)


def sanitize_file(path: str, allowed: set[str] | None, dominant_mode: bool, dry_run: bool, no_backup: bool, min_rows: int) -> dict[str, int]:
    stats = {"total": 0, "removed": 0, "kept": 0, "skipped": 0}
    try:
        rows, header, freq = analyze_file(path)
        if not header:
            stats["skipped"] += 1
            return stats
        if len(rows) < min_rows:
            stats["skipped"] += 1
            return stats
        if 'expiry_date' not in header:
            stats["skipped"] += 1
            return stats
        exp_idx = header.index('expiry_date')
        stats["total"] = len(rows)
        if allowed and not dominant_mode:
            keep_mask = [i for i, r in enumerate(rows) if len(r) > exp_idx and r[exp_idx] in allowed]
        else:
            # Dominant mode
            if not freq:
                stats["skipped"] += 1
                return stats
            dominant, _ = freq.most_common(1)[0]
            keep_mask = [i for i, r in enumerate(rows) if len(r) > exp_idx and r[exp_idx] == dominant]
        removed = len(rows) - len(keep_mask)
        stats["removed"] = removed
        stats["kept"] = len(keep_mask)
        if removed > 0:
            LOG.info("Sanitizing %s removed=%d kept=%d", path, removed, len(keep_mask))
            write_sanitized(path, header, rows, keep_mask, dry_run, no_backup)
        else:
            LOG.debug("No change %s", path)
        return stats
    except Exception as e:  # pragma: no cover
        LOG.error("Failed to sanitize %s: %s", path, e)
        stats["skipped"] += 1
        return stats


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    indices = [i.strip() for i in (args.indices.split(',') if args.indices else DEFAULT_INDICES) if i.strip()]

    provider_whitelists: dict[str, set[str]] = {}
    specified_whitelist: set[str] | None = None
    if args.allowed and not args.dominant and not args.use_provider:
        specified_whitelist = {d.strip() for d in args.allowed.split(',') if d.strip()}
    if args.use_provider:
        for idx in indices:
            wl = load_provider_allowed(idx)
            if wl:
                provider_whitelists[idx] = set(wl)
                LOG.info("Provider whitelist for %s: %s", idx, ','.join(wl))
            else:
                LOG.warning("No provider whitelist for %s; will fallback to dominant mode", idx)

    grand: dict[str, int] = defaultdict(int)
    for idx in indices:
        files = discover_option_files(args.base_dir, idx)
        if not files:
            LOG.warning("No files found for %s under %s", idx, args.base_dir)
            continue
        allowed_set = provider_whitelists.get(idx) or specified_whitelist
        for fp in files:
            st = sanitize_file(fp, allowed_set, args.dominant or (allowed_set is None), args.dry_run, args.no_backup, args.min_rows)
            for k,v in st.items():
                grand[k] += v

    LOG.info("Summary: total_rows=%d kept_rows=%d removed_rows=%d skipped_files=%d mode=%s", grand['total'], grand['kept'], grand['removed'], grand['skipped'], 'dominant' if args.dominant or (specified_whitelist is None and not args.use_provider and not provider_whitelists) else 'whitelist')
    if args.dry_run:
        LOG.info("Dry-run complete (no files modified)")

if __name__ == '__main__':
    main()
