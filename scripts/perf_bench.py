"""Performance micro-benchmark harness for diff + event serialization.

Usage (example):
  python scripts/perf_bench.py --events 2000 --panel-diffs 500 --subscribers 1000

Outputs JSON summary to stdout:
  {
    "events": 2000,
    "panel_diffs": 500,
    "subscribers": 1000,
    "serialize_p95_ms": 1.2,
    "cache_hit_ratio": 0.78,
    "avg_payload_bytes": 512
  }

Environment suggestions:
  G6_SERIALIZATION_CACHE_MAX=2048
  G6_SSE_EMIT_LATENCY_CAPTURE=1

This is a lightweight synthetic; real latency with network flush may differ.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time

from src.events.event_bus import get_event_bus
from src.utils.serialization_cache import get_serialization_cache, serialize_event


def _rand_payload(panel_n: int) -> dict:
    # Produce small changing payload to exercise diff/serialization
    return {"panel": panel_n, "value": random.random(), "ts": time.time()}


def run_bench(events: int, panel_diffs: int, subscribers: int) -> dict:
    bus = get_event_bus()
    ser_times: list[float] = []
    cache = get_serialization_cache()
    # Simulate baseline subscribers by performing serialization per subscriber (shared cache makes this cheap)
    for i in range(events):
        etype = 'panel_diff' if (i % max(1, events // max(1, panel_diffs))) == 0 else 'heartbeat'
        payload = _rand_payload(i % 100)
        start = time.time()
        # Publish once
        bus.publish(etype, payload, coalesce_key=None)
        # Simulate subscriber fan-out serialization usage (using cache directly)
        for _ in range(subscribers):
            serialize_event(etype, payload)
        ser_times.append(time.time() - start)
    total = len(ser_times)
    p95 = statistics.quantiles(ser_times, n=100)[94] if total >= 20 else max(ser_times) if ser_times else 0.0
    avg_payload_bytes: float = 0.0
    if cache._data:  # type: ignore[attr-defined]
        try:
            avg_payload_bytes = sum(len(e.data) for e in cache._data.values()) / len(cache._data)
        except Exception:
            pass
    hit_ratio = cache.hits / (cache.hits + cache.misses) if (cache.hits + cache.misses) else 0.0
    return {
        "events": events,
        "panel_diffs": panel_diffs,
        "subscribers": subscribers,
        "serialize_p95_ms": p95 * 1000.0,
        "cache_hit_ratio": hit_ratio,
        "avg_payload_bytes": avg_payload_bytes,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--events', type=int, default=500, help='Total events to publish')
    ap.add_argument('--panel-diffs', type=int, default=100, help='Approximate panel_diff count within events')
    ap.add_argument('--subscribers', type=int, default=250, help='Simulated subscriber count (fan-out scale)')
    ap.add_argument('--json', action='store_true', help='Emit JSON only')
    args = ap.parse_args()
    res = run_bench(args.events, args.panel_diffs, args.subscribers)
    out = json.dumps(res)
    if args.json:
        print(out)
    else:
        print('Benchmark Summary:')
        for k, v in res.items():
            print(f"  {k}: {v}")
        print('\nJSON:\n' + out)

if __name__ == '__main__':  # pragma: no cover
    main()
