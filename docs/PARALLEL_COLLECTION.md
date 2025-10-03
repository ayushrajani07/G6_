# Parallel/Async Collection (Experimental)

This repo includes an optional async path for parallel index collection with per-provider rate limiting. It is OFF by default and can be enabled safely via config or environment flags. The sequential path remains the default and is unchanged.

## How it works
- Async provider adapters wrap your existing provider (e.g., Kite) and execute calls in a thread pool when needed.
- A token-bucket rate limiter enforces max calls per second (cps) with an optional burst capacity.
- ParallelCollector runs per-index tasks concurrently, resolves expiry, fetches option instruments, enriches with quotes, and writes to storage.
- CSV writes remain synchronous under the hood; the collector offloads them to a small thread pool to avoid blocking the event loop.

## Enable parallel mode
- Environment variable:
  - G6_PARALLEL_COLLECTION=1
- Or in config (config.json or g6_config.json):
  ```json
  {
    "parallel_collection": {
      "enabled": true,
      "max_workers": 8,
      "rate_limits": {
        "kite": { "cps": 8.0, "burst": 16 }
      }
    }
  }
  ```

Either one of the above enables the async path at startup. If both are present, the environment variable takes precedence for enabling/disabling.

## Tuning knobs
- G6_PARALLEL_MAX_WORKERS: overrides parallel_collection.max_workers. Controls the thread pool size for blocking calls (including CSV writes).
- G6_KITE_RATE_LIMIT_CPS: overrides cps for Kite adapter.
- G6_KITE_RATE_LIMIT_BURST: overrides burst for Kite adapter.

Examples (Windows PowerShell):
- $env:G6_PARALLEL_COLLECTION = "1"; $env:G6_PARALLEL_MAX_WORKERS = "8"; python scripts/run_orchestrator_loop.py --run-once

## Safety and rollback
- Disable with G6_PARALLEL_COLLECTION=0 or remove the parallel_collection.enabled config block.
- The sequential collector path is preserved and used automatically when parallel mode is off or fails at startup. Any error will log a fallback message and the system continues with the legacy path.

## Notes
- Async providers live under src/providers/adapters and src/providers/async_factory.py.
- Parallel collector: src/collectors/parallel_collector.py.
- Rate limiter: src/providers/rate_limiter.py with tests in tests/test_rate_limiter.py.
- A smoke test for the async path exists at tests/test_parallel_collector_async_smoke.py.
