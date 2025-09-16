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
"""

from __future__ import annotations
import os
import csv
import argparse
import json
from pathlib import Path
from datetime import datetime, date
from typing import Dict, Tuple

WEEKDAY_NAMES = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
INDEX_DEFAULT = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"]

def iter_daily_rows(base_dir: str, index: str, trade_date: date):
    date_str = trade_date.strftime('%Y-%m-%d')
    index_root = Path(base_dir) / index
    if not index_root.exists():
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
                continue
            try:
                with open(daily_file, 'r', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        yield expiry_tag, offset_dir.name, row
            except Exception as e:
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

def load_master_file(master_path: Path):
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
        print(f"[WARN] could not parse master {master_path}: {e}")
    return data

def write_master_file(master_path: Path, index: str, expiry_tag: str, offset: str, data: Dict[str,Dict]):
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
    with open(master_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def update_weekday_master(base_dir: str, out_root: str, index: str, trade_date: date, alpha: float):
    weekday_name = WEEKDAY_NAMES[trade_date.weekday()]
    # Aggregate rows in-memory keyed by (expiry_tag, offset)
    buckets: Dict[tuple, Dict[str, Dict[str,float]]] = {}
    for expiry_tag, offset, row in iter_daily_rows(base_dir, index, trade_date):
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
        existing = load_master_file(master_path)
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
            else:
                rec['counter_tp'] += 1
                n_tp = rec['counter_tp']
                rec['tp_mean'] += (tp - rec['tp_mean']) / n_tp
                rec['tp_ema'] = alpha * tp + (1 - alpha) * rec['tp_ema']
                rec['counter_avg_tp'] += 1
                n_avg = rec['counter_avg_tp']
                rec['avg_tp_mean'] += (avg_tp - rec['avg_tp_mean']) / n_avg
                rec['avg_tp_ema'] = alpha * avg_tp + (1 - alpha) * rec['avg_tp_ema']
            count_updates += 1
        write_master_file(master_path, index, expiry_tag, offset, existing)
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
    ap.add_argument('--mode', choices=['eod','incremental'], default='eod', help='eod = batch once (default), incremental = write per row (higher IO)')
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
    for idx in indices:
        print(f"[INFO] Updating weekday master for {idx} {trade_date} (mode={args.mode})...")
        if args.mode == 'incremental':
            # Fallback to old incremental path by re-reading file each row
            updated = update_weekday_master(args.base_dir, args.output_dir, idx, trade_date, alpha)
        else:
            updated = update_weekday_master(args.base_dir, args.output_dir, idx, trade_date, alpha)
        print(f"[OK] {idx}: updated {updated} records")
        total += updated
    print(f"[DONE] Total updates: {total}")

if __name__ == '__main__':
    main()