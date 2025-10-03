#!/usr/bin/env python3
"""One-shot CSV write demo using AsyncMockProvider and ParallelCollector.

Writes a small set of option rows to data/g6_data_demo for quick inspection.

Usage (Windows PowerShell):

    # optional: choose a different output dir
    # $env:G6_CSV_DEMO_DIR = "data/g6_data_demo"
    python scripts/demo_write_csv_once.py

Output structure:
    data/g6_data_demo/<INDEX>/<EXPIRY_TAG>/<OFFSET>/<YYYY-MM-DD>.csv

Example file to open:
    data/g6_data_demo/NIFTY/this_week/0/<YYYY-MM-DD>.csv
"""
from __future__ import annotations

import asyncio
import os

from src.collectors.async_providers import AsyncProviders
from src.collectors.parallel_collector import ParallelCollector
from src.providers.adapters.async_mock_adapter import AsyncMockProvider
from src.storage.csv_sink import CsvSink


async def _run():
    # Relax strict weekly filters for tiny sample so at least one row passes
    os.environ.setdefault("G6_CSV_BUFFER_SIZE", "0")
    os.environ.setdefault("G6_CSV_MAX_OPEN_FILES", "8")
    os.environ.setdefault("G6_CSV_FLUSH_INTERVAL", "0.01")
    # Removed legacy CSV filter toggles (no longer used)
    # Ensure price sanity is enabled so normalization applies
    os.environ.setdefault("G6_CSV_PRICE_SANITY", "1")

    base_dir = os.environ.get("G6_CSV_DEMO_DIR", "data/g6_data_demo")
    csv_sink = CsvSink(base_dir=base_dir)

    mock = AsyncMockProvider()
    aprov = AsyncProviders(mock)

    index_params = {
        "NIFTY": {
            "enable": True,
            "expiries": ["this_week"],
            "strikes_itm": 1,
            "strikes_otm": 1,
        }
    }

    collector = ParallelCollector(aprov, csv_sink, influx_sink=None, metrics=None, max_workers=2)
    await collector.run_once(index_params)
    # Ensure buffered rows are flushed to disk for inspection
    try:
        csv_sink._buffer.flush_all()  # type: ignore[attr-defined]
    except Exception:
        pass
    print(f"CSV demo write complete at: {base_dir}")


def main():
    asyncio.run(_run())


if __name__ == "__main__":
    main()
