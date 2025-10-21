#!/usr/bin/env python3
"""weekday_master_bootstrap.py

One-time builder to generate Weekday Master overlays from existing options data.

Inputs (discovered):
  base_dir/<INDEX>/<EXPIRY_TAG>/<OFFSET>/<YYYY-MM-DD>.csv

Output (new layout & schema):
  out_dir/<INDEX>/<EXPIRY_TAG>/<OFFSET>/<WEEKDAY>.csv
  columns: timestamp,tp_mean,tp_ema,avg_tp_mean,avg_tp_ema,counter,index,expiry_tag,offset

Notes:
  - Aggregates per weekday and time-of-day (HH:MM:SS) across all available dates.
  - Arithmetic mean is true cumulative mean over days; EMA is applied across days in chronological order.
  - Within a single daily CSV, duplicate timestamps are averaged before being incorporated.
  - This script does not read existing masters; it rebuilds from source CSVs.
"""
from __future__ import annotations

import argparse
import csv
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

WEEKDAY_NAMES = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

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


@dataclass
class Args:
    base_dir: Path
    out_dir: Path
    alpha: float
    indices: list[str] | None
    expiry: list[str] | None
    offsets: list[str] | None
    market_open: str = "09:15:30"
    market_close: str = "15:30:00"


def _parse_time_key(ts: str) -> str:
    """Return HH:MM:SS from common timestamp formats (YYYY-MM-DDTHH:MM:SS or HH:MM:SS)."""
    ts = str(ts or "").strip()
    if not ts:
        return ""
    if "T" in ts:
        try:
            return ts.split("T", 1)[1][:8]
        except Exception:
            pass
    if " " in ts:
        try:
            return ts.split(" ", 1)[1][:8]
        except Exception:
            pass
    # Fallback: assume HH:MM:SS
    return ts[:8]


def _hhmmss_to_seconds(hms: str) -> int:
    try:
        h, m, s = (int(x) for x in hms.split(":", 2))
        return h * 3600 + m * 60 + s
    except Exception:
        return -1


def _compute_row_values(row: dict[str, str]) -> tuple[float, float]:
    try:
        ce = float(row.get('ce', 0) or 0)
        pe = float(row.get('pe', 0) or 0)
        avg_ce = float(row.get('avg_ce', 0) or 0)
        avg_pe = float(row.get('avg_pe', 0) or 0)
    except Exception:
        ce = pe = avg_ce = avg_pe = 0.0
    return ce + pe, avg_ce + avg_pe

def _parse_float(cell):
    try:
        if cell is None or cell == '':
            return None
        return float(cell)
    except Exception:
        return None


def _list_daily_files(offset_dir: Path) -> list[Path]:
    files = []
    try:
        for p in offset_dir.iterdir():
            if p.is_file() and p.suffix == '.csv':
                files.append(p)
    except Exception:
        return []
    # Sort by date extracted from filename YYYY-MM-DD.csv
    def _key(p: Path):
        try:
            d = date.fromisoformat(p.stem)
            return d.toordinal()
        except Exception:
            return 0
    return sorted(files, key=_key)


def _write_master(
    path: Path,
    index: str,
    expiry_tag: str,
    offset: str,
    data: dict[str, dict[str, float | int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    metric_mean_headers = [f"{n}_mean" for n in METRIC_FIELDS]
    metric_ema_headers = [f"{n}_ema" for n in METRIC_FIELDS]
    fieldnames = [
        'timestamp',
        'tp_mean',
        'tp_ema',
        'avg_tp_mean',
        'avg_tp_ema',
        *metric_mean_headers,
        *metric_ema_headers,
        'counter',
        'index',
        'expiry_tag',
        'offset',
    ]
    rows = []
    for tkey in sorted(data.keys()):
        d = data[tkey]
        rec = {
            'timestamp': tkey,
            'tp_mean': f"{float(d['tp_mean']):.6f}",
            'tp_ema': f"{float(d['tp_ema']):.6f}",
            'avg_tp_mean': f"{float(d['avg_tp_mean']):.6f}",
            'avg_tp_ema': f"{float(d['avg_tp_ema']):.6f}",
            'counter': int(d['counter']),
            'index': index,
            'expiry_tag': expiry_tag,
            'offset': offset,
        }
        for name in METRIC_FIELDS:
            rec[f'{name}_mean'] = f"{float(d.get(f'{name}_mean', 0.0)):.6f}"
        for name in METRIC_FIELDS:
            rec[f'{name}_ema'] = f"{float(d.get(f'{name}_ema', 0.0)):.6f}"
        rows.append(rec)
    tmp = path.with_suffix(path.suffix + '.tmp')
    with open(tmp, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def bootstrap(args: Args, market_open: str | None = None, market_close: str | None = None) -> None:
    base = args.base_dir
    out = args.out_dir
    alpha = float(args.alpha)

    # Resolve market window if not explicitly provided
    if market_open is None or market_close is None:
        try:
            from src.utils.timeutils import get_market_session_bounds  # type: ignore
        except Exception:  # pragma: no cover
            get_market_session_bounds = None  # type: ignore
        try:
            if get_market_session_bounds is not None:
                start_dt, end_dt = get_market_session_bounds()
                default_open = start_dt.strftime('%H:%M:%S')
                default_close = end_dt.strftime('%H:%M:%S')
            else:
                default_open, default_close = '09:15:30', '15:30:00'
        except Exception:
            default_open, default_close = '09:15:30', '15:30:00'
        market_open = market_open or default_open
        market_close = market_close or default_close

    # Aggregator: (index, expiry, offset, WEEKDAY_UPPER) -> time_key -> record
    agg: dict[tuple[str, str, str, str], dict[str, dict[str, float | int]]] = {}

    # Discover indices
    indices = args.indices or [d.name for d in base.iterdir() if d.is_dir()]
    for idx in indices:
        idx_root = base / idx
        if not idx_root.exists():
            continue
        # Discover expiries
        exp_dirs = [d for d in idx_root.iterdir() if d.is_dir()]
        if args.expiry:
            exp_dirs = [d for d in exp_dirs if d.name in set(args.expiry)]
        for exp_dir in exp_dirs:
            exp = exp_dir.name
            # Skip aggregated overview snapshots; we only want per-expiry data
            if exp.lower() == 'overview':
                continue
            # Discover offsets
            off_dirs = [d for d in exp_dir.iterdir() if d.is_dir()]
            if args.offsets:
                off_dirs = [d for d in off_dirs if d.name in set(args.offsets)]
            for off_dir in off_dirs:
                off = off_dir.name
                files = _list_daily_files(off_dir)
                if not files:
                    continue
                print(f"[BOOT] {idx}/{exp}/{off}: {len(files)} days")
                # Process chronologically to make EMA stable across days
                open_s = _hhmmss_to_seconds(market_open)
                close_s = _hhmmss_to_seconds(market_close)
                if open_s < 0 or close_s < 0 or open_s >= close_s:
                    raise ValueError(f"Invalid market window: {market_open} .. {market_close}")
                for f in files:
                    try:
                        dt = date.fromisoformat(f.stem)
                    except Exception:
                        # Skip non-date files
                        continue
                    weekday_upper = WEEKDAY_NAMES[dt.weekday()].upper()
                    key = (idx, exp, off, weekday_upper)
                    # Day-bucket aggregation to average duplicates at same time
                    sums: dict[str, dict] = {}
                    with open(f, newline='') as fh:
                        r = csv.DictReader(fh)
                        for row in r:
                            tkey = _parse_time_key(row.get('timestamp', ''))
                            if not tkey:
                                continue
                            tsec = _hhmmss_to_seconds(tkey)
                            if tsec < open_s or tsec > close_s:
                                continue
                            tp, avg_tp = _compute_row_values(row)
                            entry = sums.setdefault(tkey, {'tp': 0.0, 'avg': 0.0, 'n': 0.0, 'metrics': {}})
                            entry['tp'] += tp
                            entry['avg'] += avg_tp
                            entry['n'] += 1.0
                            # Aggregate per-metric values
                            mdict = entry['metrics']
                            for name in METRIC_FIELDS:
                                v = _parse_float(row.get(name))
                                if v is None:
                                    continue
                                slot = mdict.get(name)
                                if slot is None:
                                    slot = mdict[name] = {'sum': 0.0, 'n': 0.0}
                                slot['sum'] += float(v)
                                slot['n'] += 1.0
                    if not sums:
                        continue
                    dest = agg.setdefault(key, {})
                    for tkey, sv in sums.items():
                        tp_day = sv['tp'] / max(1.0, sv['n'])
                        avg_day = sv['avg'] / max(1.0, sv['n'])
                        # Per-day per-time metric averages
                        per_day_metrics: dict[str, float] = {}
                        mdict = sv.get('metrics') or {}
                        for name in METRIC_FIELDS:
                            slot = mdict.get(name)
                            if slot and slot.get('n', 0.0) > 0.0:
                                per_day_metrics[name] = float(slot['sum']) / float(slot['n'])
                        rec = dest.get(tkey)
                        if rec is None:
                            new_rec: dict[str, float | int] = {
                                'tp_mean': tp_day,
                                'tp_ema': tp_day,
                                'avg_tp_mean': avg_day,
                                'avg_tp_ema': avg_day,
                                'counter': 1,
                            }
                            for name in METRIC_FIELDS:
                                v = per_day_metrics.get(name, 0.0)
                                new_rec[f'{name}_mean'] = v
                                new_rec[f'{name}_ema'] = v
                            dest[tkey] = new_rec
                        else:
                            c = int(rec['counter']) + 1
                            rec['counter'] = c
                            rec['tp_mean'] = float(rec['tp_mean']) + (tp_day - float(rec['tp_mean'])) / c
                            rec['avg_tp_mean'] = float(rec['avg_tp_mean']) + (avg_day - float(rec['avg_tp_mean'])) / c
                            rec['tp_ema'] = alpha * tp_day + (1 - alpha) * float(rec['tp_ema'])
                            rec['avg_tp_ema'] = alpha * avg_day + (1 - alpha) * float(rec['avg_tp_ema'])
                            # Per-metric updates
                            for name in METRIC_FIELDS:
                                v = per_day_metrics.get(name)
                                if f'{name}_mean' not in rec:
                                    rec[f'{name}_mean'] = 0.0
                                if f'{name}_ema' not in rec:
                                    rec[f'{name}_ema'] = 0.0
                                if v is None:
                                    continue
                                rec[f'{name}_mean'] = float(rec[f'{name}_mean']) + (float(v) - float(rec[f'{name}_mean'])) / c
                                rec[f'{name}_ema'] = alpha * float(v) + (1 - alpha) * float(rec[f'{name}_ema'])

    # Write outputs
    total_files = 0
    for (idx, exp, off, wd), data in agg.items():
        out_path = out / idx / exp / off / f"{wd}.csv"
        _write_master(out_path, idx, exp, off, data)
        total_files += 1
        print(f"[WRITE] {out_path} ({len(data)} rows)")
    print(f"[DONE] Wrote {total_files} master files into {out}")


def parse_args() -> Args:
    p = argparse.ArgumentParser(description="One-time bootstrap of weekday overlay masters from historical CSVs")
    p.add_argument('--base-dir', default='data/g6_data', help='Root of live per-offset CSV data')
    p.add_argument('--output-dir', default='data/weekday_master', help='Root directory for weekday master overlays')
    p.add_argument(
        '--alpha',
        type=float,
        default=0.5,
        help='EMA alpha (0<alpha<=1) applied across days per time bucket',
    )
    p.add_argument(
        '--market-open',
        default='09:15:30',
        help='Inclusive market open time HH:MM:SS to include in overlays',
    )
    p.add_argument(
        '--market-close',
        default='15:30:00',
        help='Inclusive market close time HH:MM:SS to include in overlays',
    )
    p.add_argument('--index', dest='indices', action='append', help='Limit to specific indices (repeatable)')
    p.add_argument('--expiry', dest='expiry', action='append', help='Limit to specific expiry tags (repeatable)')
    p.add_argument('--offset', dest='offsets', action='append', help='Limit to specific offsets (repeatable)')
    a = p.parse_args()
    if not (0.0 < (a.alpha or 0.0) <= 1.0):
        raise SystemExit("--alpha must be in (0,1]")
    return Args(
        base_dir=Path(a.base_dir),
        out_dir=Path(a.output_dir),
        alpha=float(a.alpha),
        indices=a.indices,
        expiry=a.expiry,
        offsets=a.offsets,
        market_open=a.market_open,
        market_close=a.market_close,
    )


def main() -> int:
    args = parse_args()
    # Environment can override CLI defaults
    m_open = os.environ.get('G6_MARKET_OPEN', args.market_open)
    m_close = os.environ.get('G6_MARKET_CLOSE', args.market_close)
    bootstrap(args, market_open=m_open, market_close=m_close)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
