#!/usr/bin/env python3
"""
Generate per-series snapshots (TP, index price, and combined) for today's options CSVs.

Output locations:
  data/snapshot/{INDEX}/{EXPIRY_TAG}/{OFFSET}/{YYYY-MM-DD}_tp.png
  data/snapshot/{INDEX}/{EXPIRY_TAG}/{OFFSET}/{YYYY-MM-DD}_index.png
  data/snapshot/{INDEX}/{EXPIRY_TAG}/{OFFSET}/{YYYY-MM-DD}_tp_index.png

Assumptions:
- Option files are stored under data/g6_data/{INDEX}/{EXPIRY_TAG}/{OFFSET}/{YYYY-MM-DD}.csv
- Timestamp column is "timestamp" in dd-mm-YYYY HH:MM:SS (rounded 30s), but script is tolerant.
- Columns include at least 'tp' and 'index_price' (older files may lack index_price -> fallback to 'strike').
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate TP/Index snapshots for today's options files")
    p.add_argument("--base-dir", default="data/g6_data", help="Root of options CSV tree")
    p.add_argument("--out-dir", default="data/snapshot", help="Root of snapshot output")
    p.add_argument("--date", default=None, help="Date YYYY-MM-DD (defaults to today)")
    p.add_argument("--indices", default=None, help="Comma-separated list of indices to include (default: all)")
    p.add_argument("--expiries", default=None, help="Comma-separated list of expiry tags to include (default: all)")
    p.add_argument("--offsets", default=None, help="Comma-separated list of integer offsets to include (default: all)")
    return p.parse_args()


def _parse_ts(ts: str) -> dt.datetime | None:
    fmts = ["%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"]
    for f in fmts:
        try:
            return dt.datetime.strptime(ts, f)
        except Exception:
            continue
    return None


def _read_series(csv_path: Path) -> tuple[list[dt.datetime], list[float], list[float]]:
    xs: list[dt.datetime] = []
    tp_vals: list[float] = []
    idx_vals: list[float] = []
    if not csv_path.exists():
        return xs, tp_vals, idx_vals
    with csv_path.open("r", encoding="utf-8") as fh:
        rdr = csv.DictReader(fh)
        hdr = rdr.fieldnames or []
        # Backward compatible index field
        idx_field = "index_price" if "index_price" in hdr else ("strike" if "strike" in hdr else None)
        for row in rdr:
            ts = _parse_ts(row.get("timestamp", ""))
            if not ts:
                continue
            try:
                tp = float(row.get("tp", 0) or 0)
            except Exception:
                tp = 0.0
            try:
                idx = float(row.get(idx_field, 0) or 0) if idx_field else 0.0
            except Exception:
                idx = 0.0
            if tp <= 0 and idx <= 0:
                continue
            xs.append(ts)
            tp_vals.append(tp)
            idx_vals.append(idx)
    return xs, tp_vals, idx_vals


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _plot_series(xs: list[dt.datetime], ys: list[float], title: str, color: str, out_file: Path) -> None:
    if not xs or not ys:
        return
    plt.figure(figsize=(10, 4))
    # Convert datetimes to matplotlib date numbers for typing-friendly plotting
    xnums = [mdates.date2num(x) for x in xs]
    plt.plot(xnums, ys, color=color, linewidth=1.3)
    plt.gca().xaxis_date()
    plt.title(title)
    plt.tight_layout()
    _ensure_dir(out_file.parent)
    plt.savefig(out_file, dpi=120)
    plt.close()


def _plot_dual(xs: list[dt.datetime], y1: list[float], y2: list[float], title: str, out_file: Path) -> None:
    if not xs or not y1 or not y2:
        return
    plt.figure(figsize=(10, 4))
    xnums = [mdates.date2num(x) for x in xs]
    plt.plot(xnums, y1, color="tab:green", label="TP", linewidth=1.3)
    plt.plot(xnums, y2, color="tab:blue", label="Index", linewidth=1.2)
    plt.gca().xaxis_date()
    plt.title(title)
    plt.legend(loc="best")
    plt.tight_layout()
    _ensure_dir(out_file.parent)
    plt.savefig(out_file, dpi=120)
    plt.close()


def main() -> None:
    args = parse_args()
    base = Path(args.base_dir)
    out_root = Path(args.out_dir)
    date_str = args.date or dt.date.today().isoformat()

    indices_filter = set(args.indices.split(",") if args.indices else [])
    expiries_filter = set(args.expiries.split(",") if args.expiries else [])
    offsets_filter = set(int(x) for x in (args.offsets.split(",") if args.offsets else []))

    for index_dir in base.iterdir() if base.exists() else []:
        if not index_dir.is_dir():
            continue
        if index_dir.name.lower() == "overview":
            continue
        if indices_filter and index_dir.name not in indices_filter:
            continue
        for expiry_dir in index_dir.iterdir():
            if not expiry_dir.is_dir():
                continue
            if expiries_filter and expiry_dir.name not in expiries_filter:
                continue
            for offset_dir in expiry_dir.iterdir():
                if not offset_dir.is_dir():
                    continue
                off_name = offset_dir.name
                try:
                    # normalize to int representation (handles "+50")
                    off_val = int(off_name)
                except Exception:
                    try:
                        off_val = int(off_name.replace("+", ""))
                    except Exception:
                        continue
                if offsets_filter and off_val not in offsets_filter:
                    continue
                csv_file = offset_dir / f"{date_str}.csv"
                xs, tp, idx = _read_series(csv_file)
                if not xs:
                    continue
                # Outputs
                out_dir = out_root / index_dir.name / expiry_dir.name / off_name
                _plot_series(xs, tp, f"{index_dir.name} {expiry_dir.name} TP", "tab:green", out_dir / f"{date_str}_tp.png")
                _plot_series(xs, idx, f"{index_dir.name} {expiry_dir.name} Index", "tab:blue", out_dir / f"{date_str}_index.png")
                _plot_dual(xs, tp, idx, f"{index_dir.name} {expiry_dir.name} TP+Index", out_dir / f"{date_str}_tp_index.png")


if __name__ == "__main__":
    main()
