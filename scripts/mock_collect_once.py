#!/usr/bin/env python3
"""
Run a one-shot async mock collection and write CSVs to data/g6_data.
This bypasses market-hours gating and uses AsyncMockProvider.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from src.collectors.async_providers import AsyncProviders
from src.collectors.parallel_collector import ParallelCollector
from src.providers.adapters.async_mock_adapter import AsyncMockProvider
from src.storage.csv_sink import CsvSink

CONFIG_PATH = Path('config/g6_config.json')


def load_index_params():
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text())
            indices = raw.get('indices', {})
            # Normalize to ParallelCollector expected shape
            index_params = {}
            for name, cfg in indices.items():
                if not cfg.get('enable', True):
                    continue
                index_params[name] = {
                    'enable': True,
                    'expiries': cfg.get('expiries', ['this_week']),
                    'strikes_itm': int(cfg.get('strikes_itm', 5)),
                    'strikes_otm': int(cfg.get('strikes_otm', 5)),
                }
            if index_params:
                return index_params
        except Exception:
            pass
    # Fallback minimal set
    return {
        'NIFTY': {'enable': True, 'expiries': ['this_week', 'next_week', 'this_month', 'next_month'], 'strikes_itm': 2, 'strikes_otm': 2},
        'SENSEX': {'enable': True, 'expiries': ['this_week', 'next_week', 'this_month', 'next_month'], 'strikes_itm': 2, 'strikes_otm': 2},
        'BANKNIFTY': {'enable': True, 'expiries': ['this_month', 'next_month'], 'strikes_itm': 2, 'strikes_otm': 2},
        'FINNIFTY': {'enable': True, 'expiries': ['this_month', 'next_month'], 'strikes_itm': 2, 'strikes_otm': 2},
    }


async def main():
    # Ensure immediate flush for small demo runs
    import os
    os.environ.setdefault('G6_CSV_BUFFER_SIZE', '0')
    os.environ.setdefault('G6_CSV_MAX_OPEN_FILES', '16')
    os.environ.setdefault('G6_CSV_FLUSH_INTERVAL', '0.01')
    # Weekly filters default to on; ensure enabled
    # Removed legacy CSV filter toggles (no longer used)

    base_dir = 'data/g6_data'
    sink = CsvSink(base_dir=base_dir)
    aprov = AsyncProviders(AsyncMockProvider())
    collector = ParallelCollector(aprov, sink, influx_sink=None, metrics=None, max_workers=2)

    params = load_index_params()
    await collector.run_once(params)


if __name__ == '__main__':
    asyncio.run(main())
