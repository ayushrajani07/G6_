"""Sequential import diagnostic for unified collectors dependency chain.

Run:
  python -m scripts.diag_import_unified            # normal
  G6_IMPORT_TRACE=1 python -m scripts.diag_import_unified  # verbose internal trace

It imports key modules one by one printing timestamps so you can see where a hang occurs.
"""
from __future__ import annotations

import importlib
import sys
import time

MODULES = [
    'src.collectors.cycle_context',
    'src.utils.timeutils',
    'src.collectors.modules.context',
    'src.collectors.persist_result',
    'src.collectors.helpers.persist',
    'src.logstream.formatter',
    'src.utils.deprecations',
    'src.utils.market_hours',
    'src.collectors.modules.data_quality_bridge',
    'src.collectors.modules.memory_pressure_bridge',
    'src.error_handling',
    'src.utils.exceptions',
    'src.collectors.helpers.status_reducer',
    'src.collectors.unified_collectors',
]

def ts():
    return time.strftime('%H:%M:%S')

def main():
    print('[diag] starting sequential imports')
    for m in MODULES:
        start = time.perf_counter()
        print(f'[diag] import {m} ...', flush=True)
        try:
            importlib.import_module(m)
        except Exception as e:
            print(f'[diag] import {m} FAILED: {e.__class__.__name__}: {e}', flush=True)
            raise
        else:
            dur = (time.perf_counter() - start)*1000
            print(f'[diag] import {m} OK ({dur:.1f} ms)', flush=True)
    print('[diag] all imports completed')

if __name__ == '__main__':
    sys.exit(main())
