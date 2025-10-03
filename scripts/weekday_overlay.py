"""weekday_overlay.py
=======================

Purpose
-------
Maintains rolling weekday "master" overlay files for ATM option total premium (tp = ce+pe) and
its average-price equivalent (avg_tp = avg_ce + avg_pe) for every (index, expiry_tag, offset).

Hybrid Strategy (Arithmetic Mean + EMA)
--------------------------------------
For each (timestamp, index, expiry_tag, offset) pair we maintain both:
    Arithmetic mean columns:
        tp_mean       (true cumulative mean of tp)
        avg_tp_mean   (true cumulative mean of avg_tp)
    Exponential moving average columns (configurable α):
        tp_ema        (EMA over tp)
        avg_tp_ema    (EMA over avg_tp)
    Counters:
        counter_tp, counter_avg_tp (number of samples incorporated)

Update formulas given new value x and n = counter after increment:
    Arithmetic: mean_new = mean_old + (x - mean_old)/n
    EMA:        ema_new  = α * x + (1-α) * ema_old   (if first sample → ema = x)

Goal: allow plotting both a stable historical shape (means) and a responsive curve (EMA) for live comparison.

Invocation Examples (PowerShell):
  python scripts/weekday_overlay.py --base-dir data/g6_data --index NIFTY
  python scripts/weekday_overlay.py --base-dir data/g6_data --all

Outputs:
    master_overlays/<WEEKDAY>/<index>_<expiry_tag>_<offset>.csv

File schema:
    timestamp, tp_mean, tp_ema, counter_tp, avg_tp_mean, avg_tp_ema, counter_avg_tp, index, expiry_tag, offset

Assumptions:
  - Daily per-offset files already written by CsvSink in: base/index/expiry_tag/<offset>/<YYYY-MM-DD>.csv
  - Timestamps rounded to 30s boundary.

Notes on I/O strategy:
  - This script runs in EOD batch mode only (incremental mode removed).
  - It aggregates all inputs for a given date in-memory, loads each master once,
    and performs a single atomic write per affected master file.
"""

from __future__ import annotations
import os
import csv
import argparse
import json
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Tuple, List

from src.utils.overlay_quality import write_quality_report
from src.metrics import get_metrics_singleton  # facade import (soft dependency)
from src.utils.overlay_calendar import is_trading_day

WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
INDEX_DEFAULT = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]

def iter_daily_rows(base_dir: str, index: str, trade_date: date, issues: List[dict] | None = None):
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
                with open(daily_file, 'r', newline='') as f:
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

def compute_row_values(row: Dict[str,str]) -> Tuple[float,float]:
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

def load_master_file(master_path: Path, issues: List[dict] | None = None):
    if not master_path.exists():
        return {}
    data = {}
    try:
        with open(master_path, 'r', newline='') as f:
            reader = csv.DictReader(f)
            for r in reader:
                ts = r['timestamp']
                # Backward compatibility: handle legacy columns tp_avg / avg_tp_avg
                tp_mean = r.get('tp_mean') or r.get('tp_avg') or 0
                avg_tp_mean = r.get('avg_tp_mean') or r.get('avg_tp_avg') or 0
                data[ts] = {
                    'tp_mean': float(tp_mean),
                    'tp_ema': float(r.get('tp_ema') or tp_mean or 0),
                    'counter_tp': int(r.get('counter_tp',0)),
                    'avg_tp_mean': float(avg_tp_mean),
                    'avg_tp_ema': float(r.get('avg_tp_ema') or avg_tp_mean or 0),
                    'counter_avg_tp': int(r.get('counter_avg_tp',0))
                }
    except Exception as e:
        if issues is not None:
            issues.append({'type': 'parse_master_error', 'path': str(master_path), 'error': str(e)})
        print(f"[WARN] could not parse master {master_path}: {e}")
    return data

def write_master_file(master_path: Path, index: str, expiry_tag: str, offset: str, data: Dict[str,Dict], *, backup: bool = False, issues: List[dict] | None = None):
    """Atomically write the master file to disk.

    Writes to a temporary file in the same directory and then replaces the target
    to avoid partial reads by concurrent processes.
    """
    master_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['timestamp','tp_mean','tp_ema','counter_tp','avg_tp_mean','avg_tp_ema','counter_avg_tp','index','expiry_tag','offset']
    rows = []
    for ts in sorted(data.keys()):
        d = data[ts]
        rows.append({
            'timestamp': ts,
            'tp_mean': f"{d['tp_mean']:.6f}",
            'tp_ema': f"{d['tp_ema']:.6f}",
            'counter_tp': d['counter_tp'],
            'avg_tp_mean': f"{d['avg_tp_mean']:.6f}",
            'avg_tp_ema': f"{d['avg_tp_ema']:.6f}",
            'counter_avg_tp': d['counter_avg_tp'],
            'index': index,
            'expiry_tag': expiry_tag,
            'offset': offset
        })
    tmp_path = master_path.with_suffix(master_path.suffix + ".tmp")
    with open(tmp_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    # Optional backup of existing master
    if backup and master_path.exists():
        try:
            bak = master_path.with_suffix(master_path.suffix + ".bak")
            # Overwrite any previous .bak
            if bak.exists():
                bak.unlink()
            master_path.replace(bak)
            if issues is not None:
                issues.append({'type': 'backup_written', 'path': str(bak)})
        except Exception as e:
            if issues is not None:
                issues.append({'type': 'backup_error', 'path': str(master_path), 'error': str(e)})
    os.replace(tmp_path, master_path)

def update_weekday_master(base_dir: str, out_root: str, index: str, trade_date: date, alpha: float, *, issues: List[dict] | None = None, backup: bool = False):
    weekday_name = WEEKDAY_NAMES[trade_date.weekday()]
    # Aggregate rows in-memory keyed by (expiry_tag, offset)
    buckets: Dict[tuple, Dict[str, Dict[str,float]]] = {}
    for expiry_tag, offset, row in iter_daily_rows(base_dir, index, trade_date, issues):
        ts = row.get('timestamp')
        if not ts:
            continue
        tp, avg_tp = compute_row_values(row)
        key = (expiry_tag, offset)
        kdict = buckets.setdefault(key, {})
        # group by exact timestamp (already rounded by upstream)
        td = kdict.setdefault(ts, {'tp': 0.0, 'avg_tp': 0.0, 'count': 0})
        # If duplicates exist for same timestamp we average them equally
        td['tp'] += tp
        td['avg_tp'] += avg_tp
        td['count'] += 1
    count_updates = 0
    master_dir = Path(out_root) / weekday_name
    for (expiry_tag, offset), ts_map in buckets.items():
        master_path = master_dir / f"{index}_{expiry_tag}_{offset}.csv"
        existing = load_master_file(master_path, issues)
        if not ts_map:
            # No updates for this bucket; skip any write
            continue
        dirty = False
        # Normalize duplicates by dividing sums
        for ts, agg in ts_map.items():
            tp = agg['tp'] / max(1, agg['count'])
            avg_tp = agg['avg_tp'] / max(1, agg['count'])
            rec = existing.get(ts)
            if rec is None:
                existing[ts] = {
                    'tp_mean': tp,
                    'tp_ema': tp,
                    'counter_tp': 1,
                    'avg_tp_mean': avg_tp,
                    'avg_tp_ema': avg_tp,
                    'counter_avg_tp': 1
                }
                dirty = True
            else:
                # Update in place; any counter increment implies a change
                rec['counter_tp'] += 1
                n_tp = rec['counter_tp']
                rec['tp_mean'] += (tp - rec['tp_mean']) / n_tp
                rec['tp_ema'] = alpha * tp + (1 - alpha) * rec['tp_ema']
                rec['counter_avg_tp'] += 1
                n_avg = rec['counter_avg_tp']
                rec['avg_tp_mean'] += (avg_tp - rec['avg_tp_mean']) / n_avg
                rec['avg_tp_ema'] = alpha * avg_tp + (1 - alpha) * rec['avg_tp_ema']
                dirty = True
            count_updates += 1
        if dirty:
            write_master_file(master_path, index, expiry_tag, offset, existing, backup=backup, issues=issues)
    return count_updates

def main():
    ap = argparse.ArgumentParser(description="Build or update weekday master overlay averages.")
    ap.add_argument('--base-dir', default='data/g6_data', help='Root of per-offset CSV data (CsvSink output)')
    ap.add_argument('--output-dir', default='data/weekday_master', help='Root directory for weekday master overlays')
    ap.add_argument('--date', help='Target trade date (YYYY-MM-DD), defaults today')
    ap.add_argument('--index', action='append', help='Index symbol (repeatable). If omitted and --all not used, defaults set used.')
    ap.add_argument('--all', action='store_true', help='Process all default indices')
    ap.add_argument('--config', help='Path to platform config JSON (to auto-discover csv_dir, overlay alpha, output_dir)')
    ap.add_argument('--alpha', type=float, help='EMA smoothing factor α (0<α<=1). Overrides config. Default 0.5')
    args = ap.parse_args()
    cfg = {}
    if args.config:
        try:
            with open(args.config,'r') as f:
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
    trade_date = datetime.strptime(args.date, '%Y-%m-%d').date() if args.date else date.today()
    indices = []
    if args.all or not args.index:
        indices = INDEX_DEFAULT
    else:
        indices = args.index
    total = 0
    # Per-run quality summary
    run_issues: List[dict] = []
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
            'indices': args.index or INDEX_DEFAULT if (args.all or not args.index) else args.index,
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
    for idx in indices:
        print(f"[INFO] Updating weekday master for {idx} {trade_date}...")
        updated = update_weekday_master(args.base_dir, args.output_dir, idx, trade_date, alpha, issues=run_issues, backup=write_backup)
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
                        metrics.data_errors_labeled.labels(index=idx, component=comp, error_type=str(itype+'_critical')).inc()  # type: ignore[attr-defined]
                    except Exception:
                        pass
            # Also set last_run_issues per index to the count in this run and critical count gauge
            try:
                per_index_counts: Dict[str, int] = {}
                per_index_critical: Dict[str, int] = {}
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