"""
status_simulator.py

Generates a realistic runtime_status.json for demo/testing the summary_view.
- Periodically writes JSON to the given path
- Randomizes prices and ages per index
- Can include dummy analytics

Usage (via dev_tools):
  python scripts/dev_tools.py simulate-status --status-file data/runtime_status.json

This simulator is intentionally lightweight and has no external deps.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import errno
from typing import Dict, List

DEFAULT_INDICES = ["NIFTY", "BANKNIFTY", "FINNIFTY", "SENSEX"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_base_status(indices: List[str], market_open: bool, analytics: bool) -> Dict:
    now = utc_now_iso()
    status = {
        "app": {
            "name": "G6 Simulator",
            "version": "dev",
            "pid": os.getpid(),
            "host": os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME", "unknown"),
            "started_at": now,
            "uptime_sec": 0,
        },
        "market": {
            "status": "OPEN" if market_open else "CLOSED",
            "segment": "F&O",
        },
        "loop": {
            "cycle": 0,
            "last_run": now,
            "next_run_in_sec": 0,
            "avg_cycle_ms": 0,
            "p95_cycle_ms": 0,
        },
        "indices": {i: {"ltp": 0, "change": 0.0} for i in indices},
        "indices_detail": {i: {"status": "ok", "ltp": 0, "age_sec": 0} for i in indices},
        "provider": {"name": "sim", "latency_ms": random.randint(20, 80)},
        "health": {"collector": "ok", "sinks": "ok", "provider": "ok"},
        "sinks": {"csv": {"last_write": now}},
        "resources": {"cpu": random.uniform(1, 30), "rss": random.randint(50_000_000, 250_000_000)},
        "config": {"env": "dev", "output_level": "INFO"},
        "alerts": [],
        "links": {"metrics": "http://127.0.0.1:9108/metrics"},
    }
    if analytics:
        status["analytics"] = {"pcr": round(random.uniform(0.6, 1.3), 2), "max_pain": {i: random.randint(18000, 23000) for i in indices}}
    return status


def update_dynamics(state: Dict, indices: List[str], t: int, dt: float):
    # Increment cycle and uptime
    state["loop"]["cycle"] += 1
    state["app"]["uptime_sec"] = state["app"].get("uptime_sec", 0) + dt
    state["loop"]["last_run"] = utc_now_iso()
    state["loop"]["next_run_in_sec"] = max(0, int(round(state["loop"].get("target_interval", 1))))
    # Oscillate LTPs a bit with noise
    for i in indices:
        base = 20000 if i != "SENSEX" else 70000
        amp = 200 if i != "SENSEX" else 600
        ltp = base + amp * math.sin(t / 15.0) + random.uniform(-20, 20)
        prev = state["indices"][i].get("ltp", ltp)
        change = ((ltp - prev) / prev) * 100 if prev else 0.0
        state["indices"][i]["ltp"] = round(ltp, 2)
        state["indices"][i]["change"] = round(change, 2)
        state["indices_detail"][i]["ltp"] = round(ltp, 2)
        state["indices_detail"][i]["age_sec"] = random.randint(0, 5)
    # Provider latency wiggle
    state["provider"]["latency_ms"] = max(5, int(abs(50 + 30 * math.sin(t / 20.0) + random.uniform(-10, 10))))
    # Resources noise
    state["resources"]["cpu"] = max(0.5, round(abs(20 + 10 * math.sin(t / 30.0) + random.uniform(-5, 5)), 1))
    state["resources"]["rss"] = max(40_000_000, state["resources"]["rss"] + random.randint(-200_000, 300_000))



def _atomic_replace(src: Path, dst: Path, *, retries: int = 20, delay: float = 0.05) -> None:
    """Attempt an atomic replace with retries (Windows-friendly).

    On Windows, replacing a file that is opened by another process (even for reading)
    can raise PermissionError. We retry a few times with a short backoff.
    """
    # Prefer os.replace for atomicity
    import os as _os
    import time as _time
    last_err: Exception | None = None
    for _ in range(max(1, int(retries))):
        try:
            _os.replace(src, dst)
            return
        except PermissionError as e:
            last_err = e
            _time.sleep(delay)
        except OSError as e:
            # If destination is missing or other transient issues, retry a bit
            last_err = e
            _time.sleep(delay)
    # Final attempt (raise if still failing)
    _os.replace(src, dst)


def write_status(path: Path, state: Dict):
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write and flush to disk before replace
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
        try:
            f.flush()
            os.fsync(f.fileno())
        except Exception:
            pass
    _atomic_replace(tmp, path)



def main(argv: List[str]) -> int:
    p = argparse.ArgumentParser(description="Generate a runtime_status.json for demo/testing")
    p.add_argument("--status-file", default="data/runtime_status.json")
    p.add_argument("--indices", default=",".join(DEFAULT_INDICES))
    p.add_argument("--interval", type=int, default=60, help="Target seconds between real loops (for next_run display)")
    p.add_argument("--refresh", type=float, default=1.0, help="How often to update the file (seconds)")
    p.add_argument("--cycles", type=int, default=0, help="Number of updates before exit (0=infinite)")
    p.add_argument("--open-market", action="store_true")
    p.add_argument("--with-analytics", action="store_true")

    args = p.parse_args(argv)

    indices = [s.strip().upper() for s in (args.indices.split(",") if isinstance(args.indices, str) else args.indices) if s.strip()]
    status_path = Path(args.status_file)

    state = build_base_status(indices, args.open_market, args.with_analytics)
    state["loop"]["target_interval"] = args.interval

    t = 0
    remaining = args.cycles
    try:
        while True:
            t += 1
            start = time.time()
            update_dynamics(state, indices, t, args.refresh)
            write_status(status_path, state)
            if remaining:
                remaining -= 1
                if remaining <= 0:
                    break
            elapsed = time.time() - start
            sleep_for = max(0.0, args.refresh - elapsed)
            time.sleep(sleep_for)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
