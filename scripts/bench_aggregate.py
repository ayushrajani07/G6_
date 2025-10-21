#!/usr/bin/env python3
"""DEPRECATED WRAPPER: bench_aggregate.py -> bench_tools.py aggregate

Unified tool:
    python scripts/bench_tools.py aggregate --dir <dir> [--out file]

Suppress warning:
    set G6_SUPPRESS_DEPRECATIONS=1
"""
from __future__ import annotations

import os
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:  # noqa: D401
    if argv is None:
        argv = sys.argv[1:]
    if os.environ.get('G6_SUPPRESS_DEPRECATIONS','').lower() not in {'1','true','yes','on'}:
        print('[DEPRECATED] bench_aggregate.py -> use bench_tools.py aggregate', file=sys.stderr)
    return subprocess.call([sys.executable, 'scripts/bench_tools.py', 'aggregate', *argv])

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
