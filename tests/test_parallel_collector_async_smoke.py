import asyncio
import os
from datetime import date

import pytest

from src.collectors.parallel_collector import ParallelCollector
from src.collectors.async_providers import AsyncProviders
from src.providers.adapters.async_mock_adapter import AsyncMockProvider
from src.storage.csv_sink import CsvSink


def test_parallel_collector_with_mock_provider(tmp_path):
    # Use temp dir for CSV writes
    base_dir = tmp_path / "g6_data_async"
    os.environ["G6_CSV_BUFFER_SIZE"] = "0"
    os.environ["G6_CSV_MAX_OPEN_FILES"] = "8"
    os.environ["G6_CSV_FLUSH_INTERVAL"] = "0.01"
    # Legacy CSV filter toggles removed; no longer needed

    csv_sink = CsvSink(base_dir=str(base_dir))

    # Async mock provider wrapped by facade
    mock = AsyncMockProvider()
    aprov = AsyncProviders(mock)

    # Minimal index params: one index, one expiry rule, few strikes
    index_params = {
        "NIFTY": {
            "enable": True,
            "expiries": ["this_week"],
            "strikes_itm": 1,
            "strikes_otm": 1,
        }
    }

    collector = ParallelCollector(aprov, csv_sink, influx_sink=None, metrics=None, max_workers=2)

    async def _run():
        await collector.run_once(index_params)

    asyncio.run(_run())

    # Verify CSV directory created and contains summary folder for NIFTY
    nifty_dir = base_dir / "NIFTY"
    assert nifty_dir.exists(), f"Expected {nifty_dir} to exist"
    # There should be at least one expiry folder inside NIFTY (e.g., 2025-09-25)
    subdirs = [p for p in nifty_dir.iterdir() if p.is_dir()]
    assert subdirs, "Expected at least one expiry subdirectory under NIFTY"

    # Optionally check that some data files exist (not asserting exact file names)
    # Just ensure we wrote something
    found_files = False
    for sd in subdirs:
        for _ in sd.rglob("*.csv"):
            found_files = True
            break
        if found_files:
            break
    assert found_files, "Expected some CSV files to be written by ParallelCollector"
