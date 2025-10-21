#!/usr/bin/env python3
"""generate_overlay_layout_samples.py

Produce sample HTML outputs for each layout mode (by-index, grid) using synthetic data.
Tabs and split can be added later; focuses on demonstrating core rendering variations.
Generates small CSV structures in a temporary folder structure to exercise plotting script.
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Sequence

try:
    import pandas as pd  # type: ignore
except ImportError:  # pragma: no cover
    raise SystemExit("This script requires pandas. Install with: pip install pandas")
import subprocess

BASE = Path('data/_sample_overlay')
LIVE = BASE / 'g6_data'
WEEKDAY = BASE / 'weekday_master'

INDICES = ['NIFTY','BANKNIFTY']
EXPIRIES = ['this_week','next_week']
OFFSETS = ['ATM','OTM_1']

NOW = date.today()
WEEKDAY_NAME = ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'][NOW.weekday()]

random.seed(42)


def ensure_dirs() -> None:
    for idx in INDICES:
        for exp in EXPIRIES:
            for off in OFFSETS:
                (LIVE / idx / exp / off).mkdir(parents=True, exist_ok=True)
    (WEEKDAY / WEEKDAY_NAME).mkdir(parents=True, exist_ok=True)


def gen_live_csv() -> None:
    # generate 30 second buckets for 30 minutes synthetic session
    start = datetime(NOW.year, NOW.month, NOW.day, 9, 15, 0)
    rows = []
    for i in range(0, 30):  # 30 buckets ~ 15 minutes
        ts = start + timedelta(seconds=30*i)
        rows.append(ts)
    for idx in INDICES:
        for exp in EXPIRIES:
            for off in OFFSETS:
                data = []
                base_tp = random.uniform(100,150)
                for ts in rows:
                    jitter = random.uniform(-5,5)
                    ce = base_tp/2 + jitter
                    pe = base_tp/2 - jitter
                    avg_ce = ce * random.uniform(0.95,1.05)
                    avg_pe = pe * random.uniform(0.95,1.05)
                    data.append({
                        'timestamp': ts.isoformat(),
                        'ce': round(ce,2),
                        'pe': round(pe,2),
                        'avg_ce': round(avg_ce,2),
                        'avg_pe': round(avg_pe,2)
                    })
                df = pd.DataFrame(data)
                out_file = LIVE / idx / exp / off / f"{NOW:%Y-%m-%d}.csv"
                df.to_csv(out_file, index=False)


def gen_weekday_master() -> None:
    # Simplified master with mean close to base_tp and EMA slightly different
    for idx in INDICES:
        for exp in EXPIRIES:
            for off in OFFSETS:
                in_file = LIVE / idx / exp / off / f"{NOW:%Y-%m-%d}.csv"
                if not in_file.exists():
                    continue
                df = pd.read_csv(in_file)
                df['tp'] = df['ce'] + df['pe']
                df['avg_tp'] = df['avg_ce'] + df['avg_pe']
                # arithmetic mean approximated by cumulative mean
                tp_mean = []
                avg_tp_mean = []
                tp_ema = []
                avg_tp_ema = []
                alpha = 0.4
                mean_acc_tp = 0
                mean_acc_avg = 0
                for i,(t,tpv,avv) in enumerate(zip(df['timestamp'], df['tp'], df['avg_tp'], strict=False)):
                    if i == 0:
                        mean_acc_tp = tpv
                        mean_acc_avg = avv
                        tp_mean.append(tpv)
                        avg_tp_mean.append(avv)
                        tp_ema.append(tpv)
                        avg_tp_ema.append(avv)
                    else:
                        mean_acc_tp = mean_acc_tp + (tpv - mean_acc_tp)/(i+1)
                        mean_acc_avg = mean_acc_avg + (avv - mean_acc_avg)/(i+1)
                        tp_mean.append(mean_acc_tp)
                        avg_tp_mean.append(mean_acc_avg)
                        tp_ema.append(alpha*tpv + (1-alpha)*tp_ema[-1])
                        avg_tp_ema.append(alpha*avv + (1-alpha)*avg_tp_ema[-1])
                out_df = pd.DataFrame({
                    'timestamp': df['timestamp'],
                    'tp_mean': tp_mean,
                    'tp_ema': tp_ema,
                    'counter_tp': list(range(1,len(tp_mean)+1)),
                    'avg_tp_mean': avg_tp_mean,
                    'avg_tp_ema': avg_tp_ema,
                    'counter_avg_tp': list(range(1,len(avg_tp_mean)+1)),
                    'index': idx,
                    'expiry_tag': exp,
                    'offset': off
                })
                out_file = WEEKDAY / WEEKDAY_NAME / f"{idx}_{exp}_{off}.csv"
                out_df.to_csv(out_file, index=False)


def run_plot(layout: str, out_name: str) -> None:
    # Always request static export into sample_images (created if missing)
    static_dir = Path('sample_images')
    static_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, 'scripts/plot_weekday_overlays.py',
        '--live-root', str(LIVE),
        '--weekday-root', str(WEEKDAY),
        '--date', f'{NOW:%Y-%m-%d}',
        '--layout', layout,
        '--output', out_name,
        '--static-dir', str(static_dir),
        # Explicit lists (mirrors constants) so the plot script need not rely on defaults
        '--index', INDICES[0], '--index', INDICES[1],
        '--expiry-tag', EXPIRIES[0], '--expiry-tag', EXPIRIES[1],
        '--offset', OFFSETS[0], '--offset', OFFSETS[1],
        '--config-json', ''
    ]
    print('[RUN]', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def main() -> None:
    ensure_dirs()
    gen_live_csv()
    gen_weekday_master()
    run_plot('by-index','sample_by_index.html')
    run_plot('grid','sample_grid.html')
    # tabs / split not yet implemented in script logic (placeholders)

if __name__ == '__main__':
    main()
