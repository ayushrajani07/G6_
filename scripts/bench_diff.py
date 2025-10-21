#!/usr/bin/env python3
"""DEPRECATED WRAPPER: bench_diff.py -> bench_tools.py diff

Unified command:
    python scripts/bench_tools.py diff OLD.json NEW.json
"""
from __future__ import annotations

import os
import subprocess
import sys


def main(argv: list[str] | None = None) -> int:  # noqa: D401
    if argv is None:
        argv = sys.argv[1:]
    if os.environ.get('G6_SUPPRESS_DEPRECATIONS','').lower() not in {'1','true','yes','on'}:
        print('[DEPRECATED] bench_diff.py -> use bench_tools.py diff', file=sys.stderr)
    return subprocess.call([sys.executable, 'scripts/bench_tools.py', 'diff', *argv])

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
