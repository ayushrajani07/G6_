#!/usr/bin/env python3
"""Generate fresh NIFTY weekly/monthly CSV samples via CsvSink directly.

This bypasses provider/market-hours gating to demonstrate cleaned headers and rows.
"""
from __future__ import annotations

import datetime as dt
import os

from src.storage.csv_sink import CsvSink
from src.utils.timeutils import (
    compute_monthly_expiry,
    compute_weekly_expiry,
)


def build_min_chain(atm: int) -> dict[str, dict]:
    # Build a minimal, healthy CE/PE pair with positive last_price, volume, oi
    return {
        f"NFO:NIFTY{atm}CE": {
            "instrument_type": "CE",
            "strike": float(atm),
            "last_price": 15.0,
            "avg_price": 15.0,
            "volume": 1000,
            "oi": 5000,
        },
        f"NFO:NIFTY{atm}PE": {
            "instrument_type": "PE",
            "strike": float(atm),
            "last_price": 12.5,
            "avg_price": 12.5,
            "volume": 1200,
            "oi": 6000,
        },
    }


def main() -> int:
    # Relax DQ gate for this one-shot
    os.environ.setdefault("G6_CSV_DQ_MIN_POSITIVE_COUNT", "1")
    os.environ.setdefault("G6_CSV_DQ_MIN_POSITIVE_FRACTION", "0.0")
    os.environ.setdefault("G6_CSV_DEDUP_ENABLED", "0")
    # Ensure weekly filters are on
    # Removed legacy CSV filter toggles (no longer used)

    sink = CsvSink(base_dir="data/g6_data")
    index = "NIFTY"
    now = dt.datetime.now(dt.UTC)
    # Use a typical ATM for sampling
    index_price = 25180.0
    atm = 25200
    chain = build_min_chain(atm)

    today = now.date()
    this_week = compute_weekly_expiry(today, weekly_dow=3)
    this_month = compute_monthly_expiry(today, monthly_dow=3)

    # Write weekly
    sink.write_options_data(index, this_week, chain, now, index_price=index_price, index_ohlc={"high": index_price+100, "low": index_price-100}, source="script")
    # Write monthly
    sink.write_options_data(index, this_month, chain, now, index_price=index_price, index_ohlc={"high": index_price+100, "low": index_price-100}, source="script")
    # Ensure buffered rows are flushed to disk
    try:
        sink.flush()
        sink.close()
    except Exception:
        pass

    print("Wrote fresh samples for:")
    print(f"  {index} this_week={this_week} this_month={this_month}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
