#!/usr/bin/env python3
"""Dump registered metrics metadata as JSON.

Usage:
  python scripts/dump_metrics.py [--pretty]

Respects standard G6_* gating environment variables so you can probe different
enable/disable configurations quickly.
"""
from __future__ import annotations

import argparse
import json

from src.metrics import MetricsRegistry  # facade import


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--pretty', action='store_true', help='Pretty-print JSON')
    args = parser.parse_args()
    m = MetricsRegistry()
    meta = m.dump_metrics_metadata()
    if args.pretty:
        print(json.dumps(meta, indent=2, sort_keys=True))
    else:
        print(json.dumps(meta, separators=(",", ":"), sort_keys=True))

if __name__ == '__main__':  # pragma: no cover
    main()
