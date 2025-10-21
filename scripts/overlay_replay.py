#!/usr/bin/env python3
"""overlay_replay.py
Replay weekday master overlay curves as Prometheus metrics for local UI development.

What it does
- Serves Gauges on http://HOST:PORT/metrics (default 127.0.0.1:9109), same names as overlay_exporter:
    tp, avg_tp, tp_mean, tp_ema, avg_tp_mean, avg_tp_ema (all labeled by index, expiry_tag, offset)
- Iterates a weekday master CSV (<weekday>/<index>_<expiry_tag>_<offset>.csv) and updates metrics row-by-row.
- Optionally, if a live CSV for a specific trade date is provided, uses its tp/avg_tp for the live series;
    otherwise, mirrors mean to live for UI testing.

Usage examples
    python scripts/overlay_replay.py --weekday-root data/weekday_master \
        --weekday Monday --index NIFTY --expiry-tag this_week --offset 0 --speed 120

    # Use a real live CSV to drive the live lines
    python scripts/overlay_replay.py --weekday-root data/weekday_master --weekday Monday \
        --live-root data/g6_data --live-date 2025-09-12 --index NIFTY --expiry-tag this_week --offset 0

Notes
- This is a dev-only helper. It produces synthetic time progression. Prometheus will sample the ever-changing Gauges.
- Speed controls how quickly you move across rows.
- If your overlay has 60s buckets, speed=60 will run ~1 minute per second.
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

try:
    import pandas as pd  # type: ignore
    from prometheus_client import Gauge, start_http_server  # type: ignore
except Exception as e:  # noqa: BLE001
    raise SystemExit(
        f"Missing dependencies (pandas/prometheus-client): {e}"
    ) from e

WEEKDAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]


def _load_overlay_csv(root: Path, weekday: str, index: str, expiry_tag: str, offset: str) -> pd.DataFrame:
    f = root / weekday / f"{index}_{expiry_tag}_{offset}.csv"
    if not f.exists():
        raise FileNotFoundError(f"Overlay CSV not found: {f}")
    df = pd.read_csv(f)
    if df.empty or 'timestamp' not in df.columns:
        raise RuntimeError(f"Overlay CSV missing timestamp or empty: {f}")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    # Ensure expected columns exist
    for col in ['tp_mean','tp_ema','avg_tp_mean','avg_tp_ema']:
        if col not in df.columns:
            df[col] = None
    return df[['timestamp','tp_mean','tp_ema','avg_tp_mean','avg_tp_ema']]


def _load_live_csv(root: Path, index: str, expiry_tag: str, offset: str, date_str: str) -> pd.DataFrame | None:
    f = root / index / expiry_tag / offset / f"{date_str}.csv"
    if not f.exists():
        return None
    df = pd.read_csv(f)
    if df.empty or 'timestamp' not in df.columns:
        return None
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    for c in ['ce','pe','avg_ce','avg_pe']:
        if c not in df.columns:
            df[c] = 0.0
    df['tp'] = df['ce'].fillna(0) + df['pe'].fillna(0)
    df['avg_tp'] = df['avg_ce'].fillna(0) + df['avg_pe'].fillna(0)
    return df[['timestamp','tp','avg_tp']]


def _align_live_to_overlay(live: pd.DataFrame | None, overlay: pd.DataFrame) -> pd.DataFrame:
    if live is None or live.empty:
        out = overlay.copy()
        # Mirror overlay means for live to allow UI development
        out['tp'] = out['tp_mean']
        out['avg_tp'] = out['avg_tp_mean']
        return out
    # Merge nearest timestamps
    merged = pd.merge_asof(overlay.sort_values('timestamp'),
                           live.sort_values('timestamp'),
                           on='timestamp', direction='nearest', tolerance=pd.Timedelta('90s'))
    if 'tp' not in merged.columns:
        merged['tp'] = merged['tp_mean']
    if 'avg_tp' not in merged.columns:
        merged['avg_tp'] = merged['avg_tp_mean']
    return merged


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Replay weekday overlay curves to Prometheus Gauges"
    )
    p.add_argument('--weekday-root', default='data/weekday_master')
    p.add_argument(
        '--weekday',
        choices=WEEKDAYS,
        help=(
            'Weekday folder to replay (e.g., Monday). '
            'Default: current weekday'
        ),
    )
    p.add_argument('--index', required=True)
    p.add_argument('--expiry-tag', required=True)
    p.add_argument('--offset', required=True)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=9109)
    p.add_argument(
        '--interval', type=float, default=1.0, help='Seconds between steps (base)'
    )
    p.add_argument(
        '--speed',
        type=float,
        default=60.0,
        help=(
            'Rows-per-minute time compression. '
            'For 1-min buckets, 60=1min/sec'
        ),
    )
    p.add_argument(
        '--live-root',
        help='Optional root of live CSVs to drive live curves (tp/avg_tp)'
    )
    p.add_argument(
        '--live-date', help='Date of live CSV (YYYY-MM-DD) to align (optional)'
    )
    args = p.parse_args(argv)

    wk = args.weekday or WEEKDAYS[datetime.now().weekday()]  # local-ok
    overlay = _load_overlay_csv(Path(args.weekday_root), wk, args.index, args.expiry_tag, args.offset)
    live_df = None
    if args.live_root and args.live_date:
        live_df = _load_live_csv(Path(args.live_root), args.index, args.expiry_tag, args.offset, args.live_date)
    merged = _align_live_to_overlay(live_df, overlay)
    if merged.empty:
        raise SystemExit("Nothing to replay (empty merged frame)")

    # Gauges match overlay_exporter names
    g_tp = Gauge("tp", "Total premium (CE+PE) live", ["index","expiry_tag","offset"])  # type: ignore
    g_avg = Gauge("avg_tp", "Average premium (avg_ce+avg_pe) live", ["index","expiry_tag","offset"])  # type: ignore
    g_tp_mean = Gauge("tp_mean", "Weekday overlay mean(tp) at current time", ["index","expiry_tag","offset"])  # type: ignore
    g_tp_ema = Gauge("tp_ema", "Weekday overlay EMA(tp) at current time", ["index","expiry_tag","offset"])  # type: ignore
    g_avg_mean = Gauge("avg_tp_mean", "Weekday overlay mean(avg_tp) at current time", ["index","expiry_tag","offset"])  # type: ignore
    g_avg_ema = Gauge("avg_tp_ema", "Weekday overlay EMA(avg_tp) at current time", ["index","expiry_tag","offset"])  # type: ignore

    start_http_server(args.port, addr=args.host)
    print(
        f"[overlay_replay] Serving on http://{args.host}:{args.port}/metrics | "
        f"{wk} {args.index} {args.expiry_tag} {args.offset}"
    )

    labels = dict(index=args.index, expiry_tag=args.expiry_tag, offset=args.offset)
    # Estimate sleep based on speed: if speed is rows per minute, and base interval is seconds, combine both
    # We simply use args.interval / (speed/60). For speed=60 (1-min/second), sleep ~1s per row when buckets ~60s.
    scale = max(0.01, args.interval * (60.0 / max(0.1, args.speed)))
    try:
        for _, row in merged.iterrows():
            g_tp.labels(**labels).set(float(row.get('tp') or 0))
            g_avg.labels(**labels).set(float(row.get('avg_tp') or 0))
            g_tp_mean.labels(**labels).set(float(row.get('tp_mean') or 0))
            g_tp_ema.labels(**labels).set(float(row.get('tp_ema') or 0))
            g_avg_mean.labels(**labels).set(float(row.get('avg_tp_mean') or 0))
            g_avg_ema.labels(**labels).set(float(row.get('avg_tp_ema') or 0))
            time.sleep(scale)
        # Hold last values so Grafana keeps a steady last point
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    import sys as _sys
    raise SystemExit(main(_sys.argv[1:]))
