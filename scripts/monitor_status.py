#!/usr/bin/env python3
"""Lightweight runtime status monitor.
Reads a JSON status file emitted by the orchestrator (or legacy runner) and
prints concise updates when the cycle increments.

Usage:
  python scripts/monitor_status.py --file data/runtime_status.json --interval 1

Optional Rich formatting if 'rich' is installed.
"""
from __future__ import annotations

import argparse
import json
import time

try:  # optional pretty output
    from rich.console import Console  # type: ignore
    RICH = True
    console = Console()
except Exception:  # pragma: no cover
    RICH = False
    console = None  # type: ignore


from typing import Any, Mapping
from src.utils.status_reader import get_status_reader


def load_status(path: str) -> Mapping[str, Any]:
    reader = get_status_reader(path)
    data = reader.get_raw_status()
    if isinstance(data, dict):
        return data
    # Provide an empty mapping if unexpected type; callers handle missing keys
    return {}


def format_line(data: dict) -> str:
    ts = data.get("timestamp")
    cyc = data.get("cycle")
    ok = data.get("readiness_ok")
    sr = data.get("success_rate_pct")
    opts = data.get("options_last_cycle")
    ltp_reason = data.get("readiness_reason")
    sleep_sec = data.get("sleep_sec")
    return f"[{cyc}] {ts} readiness={ok} success={sr}% options={opts} sleep={sleep_sec}s {ltp_reason}"


def render_rich(data: dict) -> None:  # pragma: no cover - cosmetic
    if not RICH or console is None:
        print(format_line(data))
        return
    # Import Table lazily to avoid static analysis errors when Rich isn't installed
    from rich.table import Table  # type: ignore
    table = Table(title="G6 Runtime Status", expand=True)
    table.add_column("Field")
    table.add_column("Value")
    for k in [
        "cycle","timestamp","elapsed","interval","sleep_sec","success_rate_pct",
        "options_last_cycle","options_per_minute","api_success_rate","memory_mb","cpu_pct",
        "readiness_ok","readiness_reason"
    ]:
        table.add_row(k, str(data.get(k)))
    table.add_row("indices", ",".join(data.get("indices", [])))
    console.print(table)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default='data/runtime_status.json', help='Status JSON file path')
    ap.add_argument('--interval', type=float, default=1.0, help='Polling interval seconds')
    ap.add_argument('--rich', action='store_true', help='Force Rich table output each update (if installed)')
    args = ap.parse_args()

    reader = get_status_reader(args.file)
    last_cycle = None
    if not reader.exists():
        print(f"Waiting for status file {args.file} ...")
    while True:
        try:
            data = reader.get_raw_status()
            cyc = data.get('cycle') if isinstance(data, dict) else None
            if cyc != last_cycle:
                last_cycle = cyc
                if args.rich and RICH:
                    render_rich(data)
                else:
                    print(format_line(data))
        except FileNotFoundError:
            pass
        except json.JSONDecodeError:
            # Partial write (should be rare due to atomic replace) - skip
            pass
        except KeyboardInterrupt:
            print("Exiting monitor")
            return 0
        except Exception as e:
            print("Monitor error:", e)
        time.sleep(args.interval)


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
