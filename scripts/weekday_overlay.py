"""weekday_overlay.py (re-written)
=================================

Goal
----
End-of-day updater for "weekday master" overlays of option total premium families.

New layout and schema (as requested):

Directory layout (masters):
    data/weekday_master/<INDEX>/<EXPIRY_TAG>/<OFFSET>/<WEEKDAY>.csv

Where:
    - INDEX ∈ {NIFTY, BANKNIFTY, SENSEX, FINNIFTY}
    - EXPIRY_TAG ∈ {this_week, next_week, this_month, next_month}
    - OFFSET ∈ {0, +50, -50, +100, -100, +150, ...}
    - WEEKDAY ∈ {MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY}

Daily inputs (from collectors via CsvSink):
    data/g6_data/<INDEX>/<EXPIRY_TAG>/<OFFSET>/<YYYY-MM-DD>.csv

CSV schema for masters (per row):
    timestamp, tp_mean, tp_ema, avg_tp_mean, avg_tp_ema, counter, index, expiry_tag, offset

Semantics
---------
- At EOD, consume the day CSV (tp = ce+pe, avg_tp = avg_ce+avg_pe).
- For each HH:MM:SS timestamp, upsert mean and EMA for tp and avg_tp.
- Use a single counter per timestamp (increments by 1 on each update).
- Replace any existing values for that timestamp; write atomically.

Notes
-----
- Timestamps are treated verbatim (use upstream rounding if needed).
- The updater is idempotent for the same inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections.abc import Generator
from datetime import date, datetime
from pathlib import Path
from typing import Any

# Ensure repository root is on sys.path when invoked as a script
# This avoids ModuleNotFoundError for 'src' when running via `python scripts/weekday_overlay.py`
import sys  # isort: skip
try:
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
except Exception:
    # Non-fatal; if this fails the caller can set PYTHONPATH instead
    pass

from src.metrics import get_metrics_singleton  # facade import (soft dependency)
from src.utils.overlay_calendar import is_trading_day
from src.utils.overlay_quality import write_quality_report
from src.utils.timeutils import get_market_session_bounds  # shared market-hours source

# File-naming weekday (Title-case) and requested uppercase variant for file names
WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
WEEKDAY_NAMES_UPPER = [w.upper() for w in WEEKDAY_NAMES]

INDEX_DEFAULT = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]

# Additional per-row option metrics to aggregate (mean and EMA per timestamp)
METRIC_FIELDS = [
    'ce_vol', 'pe_vol',
    'ce_oi', 'pe_oi',
    'ce_iv', 'pe_iv',
    'ce_delta', 'pe_delta',
    'ce_theta', 'pe_theta',
    'ce_vega', 'pe_vega',
    'ce_gamma', 'pe_gamma',
    'ce_rho', 'pe_rho',
]


def _parse_time_key(ts: str) -> str:
    """Extract HH:MM:SS from common timestamp representations.

    Accepts formats like 'YYYY-MM-DDTHH:MM:SS', 'YYYY-MM-DD HH:MM:SS', or 'HH:MM:SS'.
    Returns empty string on failure.
    """
    ts = str(ts or "").strip()
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
    # Fallback assume already HH:MM:SS
    return ts[:8]


def _hhmmss_to_seconds(hms: str) -> int:
    try:
        h, m, s = (int(x) for x in hms.split(":", 2))
        return h * 3600 + m * 60 + s
    except Exception:
        return -1


def iter_daily_rows(
    base_dir: str,
    index: str,
    trade_date: date,
    issues: list[dict] | None = None,
) -> Generator[tuple[str, str, dict[str, str]], None, None]:
    date_str = trade_date.strftime('%Y-%m-%d')
    index_root = Path(base_dir) / index
    if not index_root.exists():
        if issues is not None:
            issues.append({
                'type': 'missing_index_root', 'index': index, 'path': str(index_root)
            })
        return
    for expiry_tag_dir in index_root.iterdir():
        if not expiry_tag_dir.is_dir():
            continue
        expiry_tag = expiry_tag_dir.name
        # Skip overview or unrelated directories
        if expiry_tag == 'overview':
            continue
        for offset_dir in expiry_tag_dir.iterdir():
            if not offset_dir.is_dir():
                continue
            daily_file = offset_dir / f"{date_str}.csv"
            if not daily_file.exists():
                if issues is not None:
                    issues.append({
                        'type': 'missing_daily_csv', 'index': index, 'expiry_tag': expiry_tag,
                        'offset': offset_dir.name, 'path': str(daily_file)
                    })
                continue
            try:
                with open(daily_file, newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        yield expiry_tag, offset_dir.name, row
            except Exception as e:
                if issues is not None:
                    issues.append({
                        'type': 'read_error', 'index': index, 'expiry_tag': expiry_tag,
                        'offset': offset_dir.name, 'path': str(daily_file), 'error': str(e)
                    })
                print(f"[WARN] read fail {daily_file}: {e}")


def _normalize_indices(indices: list[str] | None) -> list[str]:
    """Normalize user-provided indices.

    - Accepts comma-separated tokens in each entry
    - Uppercases values and deduplicates while preserving order
    - Filters to known defaults; unknowns are ignored with a warning
    """
    if not indices:
        return INDEX_DEFAULT
    seen: set[str] = set()
    result: list[str] = []
    for entry in indices:
        # allow comma-separated
        parts = [p.strip() for p in str(entry).split(',') if p.strip()]
        for p in parts:
            u = p.upper()
            if u in seen:
                continue
            if u not in INDEX_DEFAULT:
                print(f"[WARN] Unknown index '{p}' ignored; allowed: {','.join(INDEX_DEFAULT)}")
                continue
            seen.add(u)
            result.append(u)
    return result or INDEX_DEFAULT

def compute_row_values(row: dict[str, str]) -> tuple[float, float]:
    # Derive tp and avg_tp robustly
    try:
        ce = float(row.get('ce', 0) or 0)
        pe = float(row.get('pe', 0) or 0)
        avg_ce = float(row.get('avg_ce', 0) or 0)
        avg_pe = float(row.get('avg_pe', 0) or 0)
    except Exception:
        ce = pe = avg_ce = avg_pe = 0.0
    tp = ce + pe
    avg_tp = avg_ce + avg_pe
    return tp, avg_tp

def _parse_float(cell: str | float | int | None) -> float | None:
    try:
        if cell is None or cell == '':
            return None
        return float(cell)
    except Exception:
        return None

def _to_float_str(cell: str | None) -> float:
    """Parse a CSV string cell to float with safe defaults."""
    if cell is None:
        return 0.0
    s = cell.strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except Exception:
        return 0.0

def _to_int_str(cell: str | None) -> int:
    """Parse a CSV string cell to int with safe defaults."""
    if cell is None:
        return 0
    s = cell.strip()
    if s == "":
        return 0
    try:
        return int(float(s))
    except Exception:
        return 0

def load_master_file(master_path: Path, issues: list[dict] | None = None) -> dict[str, dict[str, float | int]]:
    """Load the NEW schema masters (with single 'counter').

    Backward compatibility: if file is in legacy schema, we map counters to a single 'counter'.
    Returns a dict: ts -> {tp_mean,tp_ema,avg_tp_mean,avg_tp_ema,<metrics...>,counter}
    """
    if not master_path.exists():
        return {}
    data: dict[str, dict[str, float | int]] = {}
    try:
        with open(master_path, newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = str(r.get('timestamp') or '')
                if not ts:
                    continue
                # Handle both new and legacy names
                tp_mean_s = r.get('tp_mean')
                if tp_mean_s in (None, ''):
                    tp_mean_s = r.get('tp_avg')
                avg_tp_mean_s = r.get('avg_tp_mean')
                if avg_tp_mean_s in (None, ''):
                    avg_tp_mean_s = r.get('avg_tp_avg')
                tp_ema_s = r.get('tp_ema')
                if tp_ema_s in (None, ''):
                    tp_ema_s = tp_mean_s
                avg_tp_ema_s = r.get('avg_tp_ema')
                if avg_tp_ema_s in (None, ''):
                    avg_tp_ema_s = avg_tp_mean_s
                tp_mean = _to_float_str(tp_mean_s)
                avg_tp_mean = _to_float_str(avg_tp_mean_s)
                tp_ema = _to_float_str(tp_ema_s)
                avg_tp_ema = _to_float_str(avg_tp_ema_s)
                # Counters: new 'counter' or legacy pair
                c_s = r.get('counter')
                if c_s in (None, ''):
                    # derive from legacy
                    ctp = _to_int_str(r.get('counter_tp'))
                    cav = _to_int_str(r.get('counter_avg_tp'))
                    c = max(ctp, cav)
                else:
                    c = _to_int_str(c_s)
                rec: dict[str, float | int] = {
                    'tp_mean': tp_mean,
                    'tp_ema': tp_ema,
                    'avg_tp_mean': avg_tp_mean,
                    'avg_tp_ema': avg_tp_ema,
                    'counter': int(c),
                }
                # Load additional metric fields if present; else default to 0.0
                for name in METRIC_FIELDS:
                    m_mean = r.get(f'{name}_mean')
                    m_ema = r.get(f'{name}_ema')
                    rec[f'{name}_mean'] = _to_float_str(m_mean)
                    rec[f'{name}_ema'] = _to_float_str(m_ema)
                data[ts] = rec
    except Exception as e:
        if issues is not None:
            issues.append({'type': 'parse_master_error', 'path': str(master_path), 'error': str(e)})
        print(f"[WARN] could not parse master {master_path}: {e}")
    return data

def write_master_file_new_schema(
    master_path: Path,
    index: str,
    expiry_tag: str,
    offset: str,
    data: dict[str, dict[str, float | int]],
    *,
    backup: bool = False,
    issues: list[dict] | None = None,
) -> None:
    """Write masters in the NEW schema with a single 'counter'."""
    master_path.parent.mkdir(parents=True, exist_ok=True)
    # Stable header order: core tp/avg_tp metrics, then per-option metrics (mean then ema), then metadata
    metric_mean_headers = [f"{n}_mean" for n in METRIC_FIELDS]
    metric_ema_headers = [f"{n}_ema" for n in METRIC_FIELDS]
    fieldnames = (
        ['timestamp', 'tp_mean', 'tp_ema', 'avg_tp_mean', 'avg_tp_ema']
        + metric_mean_headers
        + metric_ema_headers
        + ['counter', 'index', 'expiry_tag', 'offset']
    )
    rows = []
    for ts in sorted(data.keys()):
        d: dict[str, float | int] = data[ts]
        rec = {
            'timestamp': ts,
            'tp_mean': f"{d['tp_mean']:.6f}",
            'tp_ema': f"{d['tp_ema']:.6f}",
            'avg_tp_mean': f"{d['avg_tp_mean']:.6f}",
            'avg_tp_ema': f"{d['avg_tp_ema']:.6f}",
            'counter': int(d['counter']),
            'index': index,
            'expiry_tag': expiry_tag,
            'offset': offset
        }
        # Fill additional metric columns, defaulting to 0.0 if missing
        for name in METRIC_FIELDS:
            rec[f'{name}_mean'] = f"{float(d.get(f'{name}_mean', 0.0)):.6f}"
        for name in METRIC_FIELDS:
            rec[f'{name}_ema'] = f"{float(d.get(f'{name}_ema', 0.0)):.6f}"
        rows.append(rec)
    tmp_path = master_path.with_suffix(master_path.suffix + ".tmp")
    with open(tmp_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    if backup and master_path.exists():
        try:
            bak = master_path.with_suffix(master_path.suffix + ".bak")
            if bak.exists():
                bak.unlink()
            master_path.replace(bak)
            if issues is not None:
                issues.append({'type': 'backup_written', 'path': str(bak)})
        except Exception as e:
            if issues is not None:
                issues.append({'type': 'backup_error', 'path': str(master_path), 'error': str(e)})
    os.replace(tmp_path, master_path)


## Legacy flat write removed by request

def update_weekday_master(
    base_dir: str,
    out_root: str,
    index: str,
    trade_date: date,
    alpha: float,
    *,
    issues: list[dict] | None = None,
    backup: bool = False,
    market_open: str = "09:15:30",
    market_close: str = "15:30:00",
) -> int:
    """Update weekday masters for a given index on the given trade_date.

    - Reads inputs from base_dir/<index>/<expiry>/<offset>/<YYYY-MM-DD>.csv
    - Writes outputs to out_root/<index>/<expiry>/<offset>/<WEEKDAY>.csv (NEW schema)
    - Also writes legacy flat file at out_root/<Weekday>/<index>_<expiry>_<offset>.csv for compatibility.
    Returns: number of timestamps updated across all (expiry, offset).
    """
    weekday_idx = trade_date.weekday()
    weekday_name_upper = WEEKDAY_NAMES_UPPER[weekday_idx]

    # Aggregate rows in-memory keyed by (expiry_tag, offset)
    buckets: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    open_s = _hhmmss_to_seconds(market_open)
    close_s = _hhmmss_to_seconds(market_close)
    if open_s < 0 or close_s < 0 or open_s >= close_s:
        raise ValueError(f"Invalid market window: {market_open} .. {market_close}")
    for expiry_tag, offset, row in iter_daily_rows(base_dir, index, trade_date, issues):
        ts = _parse_time_key(row.get('timestamp', ''))
        if not ts:
            continue
        # Keep only rows within trading window (inclusive)
        tsec = _hhmmss_to_seconds(ts)
        if tsec < open_s or tsec > close_s:
            continue
        tp, avg_tp = compute_row_values(row)
        # Prepare or update aggregation entry for this timestamp
        key = (expiry_tag, offset)
        kdict = buckets.setdefault(key, {})
        td: dict[str, Any] = kdict.setdefault(ts, {'tp': 0.0, 'avg_tp': 0.0, 'count': 0.0, 'metrics': {}})
        td['tp'] += tp
        td['avg_tp'] += avg_tp
        td['count'] += 1.0
        # Aggregate additional metric fields per-day per-time (average duplicates later)
        mdict: dict[str, Any] = td['metrics']
        for name in METRIC_FIELDS:
            v = _parse_float(row.get(name))
            if v is None:
                continue
            mslot = mdict.get(name)
            if mslot is None:
                mslot = mdict[name] = {'sum': 0.0, 'n': 0.0}
            mslot['sum'] += float(v)
            mslot['n'] += 1.0

    count_updates = 0
    out_root_path = Path(out_root)

    for (expiry_tag, offset), ts_map in buckets.items():
        if not ts_map:
            continue
        # New layout path only
        new_dir = out_root_path / index / expiry_tag / offset
        new_path = new_dir / f"{weekday_name_upper}.csv"

        # Load existing (new layout)
        existing: dict[str, dict[str, float | int]] = load_master_file(new_path, issues)

        dirty = False
        for ts, agg in ts_map.items():
            tp = agg['tp'] / max(1.0, agg['count'])
            avg_tp = agg['avg_tp'] / max(1.0, agg['count'])
            # Compute per-day values for metrics if present
            per_day_metrics: dict[str, float] = {}
            mdict = agg.get('metrics') or {}
            for name in METRIC_FIELDS:
                slot = mdict.get(name)
                if slot and slot.get('n', 0.0) > 0.0:
                    per_day_metrics[name] = float(slot['sum']) / float(slot['n'])

            rec = existing.get(ts)
            if rec is None:
                new_rec: dict[str, float | int] = {
                    'tp_mean': tp,
                    'tp_ema': tp,
                    'avg_tp_mean': avg_tp,
                    'avg_tp_ema': avg_tp,
                    'counter': 1,
                }
                # Initialize metric values if available; else zeros
                for name in METRIC_FIELDS:
                    v = per_day_metrics.get(name, 0.0)
                    new_rec[f'{name}_mean'] = v
                    new_rec[f'{name}_ema'] = v
                existing[ts] = new_rec
                dirty = True
            else:
                # Single counter
                c = int(rec.get('counter', 0)) + 1
                rec['counter'] = c
                # Arithmetic means (true cumulative)
                rec['tp_mean'] = float(rec['tp_mean']) + (tp - float(rec['tp_mean'])) / c
                rec['avg_tp_mean'] = float(rec['avg_tp_mean']) + (avg_tp - float(rec['avg_tp_mean'])) / c
                # EMA updates
                rec['tp_ema'] = alpha * tp + (1 - alpha) * float(rec['tp_ema'])
                rec['avg_tp_ema'] = alpha * avg_tp + (1 - alpha) * float(rec['avg_tp_ema'])
                # Update per-metric aggregates only if we observed a value today for that metric
                for name in METRIC_FIELDS:
                    v = per_day_metrics.get(name)
                    # Ensure fields exist
                    if f'{name}_mean' not in rec:
                        rec[f'{name}_mean'] = 0.0
                    if f'{name}_ema' not in rec:
                        rec[f'{name}_ema'] = 0.0
                    if v is None:
                        continue
                    rec[f'{name}_mean'] = float(rec[f'{name}_mean']) + (float(v) - float(rec[f'{name}_mean'])) / c
                    rec[f'{name}_ema'] = alpha * float(v) + (1 - alpha) * float(rec[f'{name}_ema'])
                dirty = True
            count_updates += 1

        if dirty:
            # Write NEW schema/layout only
            write_master_file_new_schema(new_path, index, expiry_tag, offset, existing, backup=backup, issues=issues)

    return count_updates

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Build or update weekday master overlay averages (new layout).",
    )
    ap.add_argument(
        '--base-dir',
        default='data/g6_data',
        help='Root of per-offset CSV data (CsvSink output)',
    )
    ap.add_argument(
        '--output-dir',
        default='data/weekday_master',
        help='Root directory for weekday master overlays (new layout root)',
    )
    ap.add_argument('--date', help='Target trade date (YYYY-MM-DD), defaults today')
    ap.add_argument(
        '--index',
        action='append',
        help='Index symbol (repeatable). If omitted and --all not used, defaults set used.',
    )
    ap.add_argument('--all', action='store_true', help='Process all default indices')
    ap.add_argument(
        '--config',
        help='Path to platform config JSON (to auto-discover csv_dir, overlay alpha, output_dir)',
    )
    ap.add_argument(
        '--alpha',
        type=float,
        help='EMA smoothing factor α (0<α<=1). Overrides config. Default 0.5',
    )
    ap.add_argument(
        '--market-open',
        help='Override inclusive market open time HH:MM:SS; default comes from timeutils.get_market_session_bounds()',
    )
    ap.add_argument(
        '--market-close',
        help='Override inclusive market close time HH:MM:SS; default comes from timeutils.get_market_session_bounds()',
    )
    args = ap.parse_args()
    # Validate and normalize inputs without changing the CLI surface
    # Base/output dirs
    if not os.path.isdir(args.base_dir):
        print(f"[WARN] Base directory does not exist: {args.base_dir}")
    try:
        Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    except Exception as e:
        raise SystemExit(f"Cannot create output directory '{args.output_dir}': {e}") from e

    cfg = {}
    if args.config:
        try:
            with open(args.config) as f:
                cfg = json.load(f)
        except Exception as e:
            print(f"[WARN] Could not load config {args.config}: {e}")
    # discover base dir
    if args.base_dir == 'data/g6_data' and cfg:
        args.base_dir = cfg.get('storage',{}).get('csv_dir', args.base_dir)
    # overlay settings
    overlay_cfg = cfg.get('overlays',{}).get('weekday',{}) if cfg else {}
    alpha = args.alpha if args.alpha is not None else overlay_cfg.get('alpha', 0.5)
    out_dir_cfg = overlay_cfg.get('output_dir')
    if args.output_dir == 'data/weekday_master' and out_dir_cfg:
        args.output_dir = out_dir_cfg
    if not (0 < alpha <= 1):
        raise SystemExit("Alpha must be in (0,1]")
    # Date validation
    try:
        trade_date = datetime.strptime(args.date, '%Y-%m-%d').date() if args.date else date.today()
    except Exception as e:
        raise SystemExit(f"Invalid --date '{args.date}': {e}") from e

    # Indices normalization (accept comma-separated, case-insensitive)
    indices = _normalize_indices(args.index if not args.all else INDEX_DEFAULT)
    total = 0
    # Per-run quality summary
    run_issues: list[dict] = []
    backup_env = os.environ.get('G6_OVERLAY_WRITE_BACKUP', '0')
    write_backup = backup_env.strip() not in ('', '0', 'false', 'False')
    # Optional skip if non-trading day
    skip_non_trading_env = os.environ.get('G6_OVERLAY_SKIP_NON_TRADING', '0')
    skip_non_trading = skip_non_trading_env.strip() not in ('', '0', 'false', 'False')
    if skip_non_trading and not is_trading_day(trade_date):
        info = {
            'type': 'non_trading_day_skipped',
            'date': f"{trade_date:%Y-%m-%d}",
        }
        run_issues.append(info)
        print(f"[INFO] Non-trading day {trade_date:%Y-%m-%d} skipped by config (G6_OVERLAY_SKIP_NON_TRADING)")
        # Still produce a quality report and metrics, then exit early
        summary = {
            'indices': indices,
            'base_dir': args.base_dir,
            'output_dir': args.output_dir,
            'alpha': alpha,
            'total_updates': total,
            'issues': run_issues,
        }
        try:
            report_path = write_quality_report(
                args.output_dir,
                trade_date,
                WEEKDAY_NAMES[trade_date.weekday()],
                summary,
            )
            print(f"[INFO] Quality report: {report_path}")
        except Exception as e:
            print(f"[WARN] Failed to write quality report: {e}")
        # Opportunistic metrics: set freshness
        try:
            metrics = get_metrics_singleton()
            if metrics is not None:
                try:
                    import time as _time
                    metrics.overlay_quality_last_report_unixtime.set(_time.time())  # type: ignore[attr-defined]
                    metrics.overlay_quality_last_run_total_issues.set(len(run_issues))  # type: ignore[attr-defined]
                except Exception:
                    pass
        except Exception:
            pass
        return
    # Resolve market window from shared utility unless overridden
    try:
        start_dt, end_dt = get_market_session_bounds(trade_date)
        default_open = start_dt.strftime('%H:%M:%S')
        default_close = end_dt.strftime('%H:%M:%S')
    except Exception:
        default_open, default_close = '09:15:30', '15:30:00'
    mo = args.market_open or os.environ.get('G6_MARKET_OPEN') or default_open
    mc = args.market_close or os.environ.get('G6_MARKET_CLOSE') or default_close

    for idx in indices:
        print(f"[INFO] Updating weekday master for {idx} {trade_date}...")
        updated = update_weekday_master(
            args.base_dir,
            args.output_dir,
            idx,
            trade_date,
            alpha,
            issues=run_issues,
            backup=write_backup,
            market_open=mo,
            market_close=mc,
        )
        print(f"[OK] {idx}: updated {updated} records")
        total += updated
    print(f"[DONE] Total updates: {total}")
    # Emit quality report
    summary = {
        'indices': indices,
        'base_dir': args.base_dir,
        'output_dir': args.output_dir,
        'alpha': alpha,
        'total_updates': total,
        'issues': run_issues,
    }
    try:
        report_path = write_quality_report(args.output_dir, trade_date, WEEKDAY_NAMES[trade_date.weekday()], summary)
        print(f"[INFO] Quality report: {report_path}")
    except Exception as e:
        print(f"[WARN] Failed to write quality report: {e}")

    # Opportunistically emit metrics based on issues
    try:
        metrics = get_metrics_singleton()
        if metrics is not None:
            # Set freshness gauge
            try:
                import time as _time
                metrics.overlay_quality_last_report_unixtime.set(_time.time())  # type: ignore[attr-defined]
            except Exception:
                pass
        if metrics is not None and run_issues:
            # Map issue types to severity and labels
            critical_types = {
                'missing_index_root',
                'parse_master_error',
                'read_error',
            }
            # Total issues
            try:
                metrics.overlay_quality_last_run_total_issues.set(len(run_issues))  # type: ignore[attr-defined]
            except Exception:
                pass
            for issue in run_issues:
                itype = issue.get('type', 'unknown')
                idx = issue.get('index') or 'unknown'
                comp = 'weekday_overlay'
                # Emit labeled data error counter for visibility
                try:
                    metrics.data_errors_labeled.labels(index=idx, component=comp, error_type=str(itype)).inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
                # Aggregate DQ issues per index
                try:
                    metrics.index_dq_issues_total.labels(index=idx).inc()  # type: ignore[attr-defined]
                except Exception:
                    pass
                # Future: a dedicated alerts gauge could be toggled for critical issues
                if itype in critical_types:
                    # For now, we simply increment again to make criticals more visible in rate
                    try:
                        ctr = getattr(metrics, 'data_errors_labeled', None)
                        if ctr is not None:
                            ctr.labels(index=idx, component=comp, error_type=str(itype + '_critical')).inc()
                    except Exception:
                        pass
            # Also set last_run_issues per index to the count in this run and critical count gauge
            try:
                per_index_counts: dict[str, int] = {}
                per_index_critical: dict[str, int] = {}
                for issue in run_issues:
                    idx = issue.get('index') or 'unknown'
                    per_index_counts[idx] = per_index_counts.get(idx, 0) + 1
                    if issue.get('type') in critical_types:
                        per_index_critical[idx] = per_index_critical.get(idx, 0) + 1
                for k, v in per_index_counts.items():
                    try:
                        metrics.overlay_quality_last_run_issues.labels(index=k).set(v)  # type: ignore[attr-defined]
                    except Exception:
                        pass
                for k, v in per_index_critical.items():
                    try:
                        metrics.overlay_quality_last_run_critical.labels(index=k).set(v)  # type: ignore[attr-defined]
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        # Never break the run if metrics emission fails
        pass

if __name__ == '__main__':
    main()
