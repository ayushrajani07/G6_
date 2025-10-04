# Emission Batcher Enhancements

Current implementation (`src/metrics/emission_batcher.py`):
- Counter coalescing (accumulate increments keyed by metric + label tuple).
- Env-gated enable/disable.
- Internal self-metrics (queue depth gauge, flush counters) exposed via spec (e.g., `g6_metrics_batch_queue_depth`).
- Synchronous flush on tick / time / size threshold (basic heuristics).

## Objectives
1. Reduce lock contention and allocation churn under high-frequency counter increments.
2. Bound per-scrape variability (avoid bursty scrape latency from large flush spikes).
3. Provide adaptive backpressure signals if application emission rate outpaces flush throughput.
4. Extend batching to selected histogram observations (optional) without distorting statistical meaning.

## Roadmap (Phases)
| Phase | Feature | Rationale | Success Criteria |
|-------|---------|-----------|------------------|
| P1 | Adaptive flush sizing | Avoid constant-size flush; adapt to observed increment rate | p95 flush batch size target within [X,Y] range (configurable) – PARTIAL IMPLEMENTATION: EWMA target sizing + instrumentation merged; still pending: proactive flush-on-size trigger & max interval guard |
| P2 | Async flush worker (queue + worker thread) | Remove emission path blocking when flush latency increases | <5% of increments experience >1ms lock wait at 5x baseline load |
| P3 | Histogram pre-aggregation buckets | Coalesce frequent small observations; reduce allocation | Histogram sample emit rate reduced >40% w/ <2% quantile deviation |
| P4 | Priority lanes (hot metrics) | Ensure SLO-critical counters flush promptly | Hot lane max delay < target (e.g. 250ms) under stress |
| P5 | Adaptive spillover & shedding | Protect process under extreme surge | No OOM; shedding metric exports a counter of dropped increments |

## Design Details
### Adaptive Flush Sizing
Maintain exponentially weighted moving average (EWMA) of increments/sec. Compute target batch size = clamp( rate * target_interval , min_batch, max_batch ). Trigger flush when either size >= target_batch or elapsed >= max_interval.

### Async Flush Worker
Structure:
```
Producer threads -> lock-free ring buffer (or mutex-protected list) -> flush worker thread -> Prom client
```
Fallback to synchronous flush if worker backlog exceeds safety threshold to avoid unbounded growth.

### Histogram Pre-Aggregation
Approach: Edge-quantize observed values into bucket counters locally, then emit a single batch update per scrape interval by incrementing `_bucket` counters directly. Guard rails:
- Restrict to whitelisted histograms (env `G6_BATCH_HIST_WHITELIST` list of metric names)
- Track distortion: compare raw vs batched count/sum over a sampling window (export deviation gauges)

### Priority Lanes
Maintain two queues: HOT and NORMAL. HOT metrics (configurable list) are always flushed first; if flush budget (time slice) exceeded, normal queue may defer to next cycle.

### Backpressure & Shedding
If combined queue length > high_watermark:
1. Increment `g6_metrics_batch_backpressure_events_total` (new counter)
2. Shorten flush interval (aggressive drain mode)
3. If still > critical_watermark for N cycles, begin shedding lowest-priority increments (increment `g6_metrics_batch_shed_total`).

## New / Extended Metrics (Proposed)
| Metric | Type | Labels | Purpose |
|--------|------|--------|---------|
| g6_metrics_batch_flush_duration_ms | histogram |  | Flush path latency distribution |
| g6_metrics_batch_flush_increments | gauge |  | Increments emitted in last flush |
| g6_metrics_batch_adaptive_target | gauge |  | Current adaptive target batch size |
| g6_metrics_batch_backpressure_events_total | counter |  | Backpressure episodes encountered |
| g6_metrics_batch_shed_total | counter | reason | Dropped increments (reasons: overflow, shutdown) |
| g6_metrics_batch_hist_quantile_deviation | gauge | metric | Relative deviation raw vs batched (trial mode) |

## Configuration
| Env Var | Default | Description |
|---------|---------|-------------|
| G6_EMISSION_BATCH_MAX_INTERVAL_MS | 500 | Hard ceiling flush interval |
| G6_EMISSION_BATCH_TARGET_INTERVAL_MS | 200 | Adaptive target interval baseline |
| G6_EMISSION_BATCH_MIN_SIZE | 50 | Min batch size (adaptive lower bound) |
| G6_EMISSION_BATCH_MAX_SIZE | 5000 | Max batch size (adaptive upper bound) |
| G6_EMISSION_BATCH_ASYNC | 0 | Enable async worker |
| G6_BATCH_HIST_WHITELIST | (empty) | Comma list of histogram metric names for pre-agg |
| G6_BATCH_PRIORITY_HOT | (empty) | Comma list of counter metric names treated as HOT |
| G6_BATCH_BACKPRESSURE_HIGH | 20000 | Queue size high watermark |
| G6_BATCH_BACKPRESSURE_CRITICAL | 40000 | Queue size critical watermark |

## Open Questions / Risks
- Histogram semantic fidelity: direct bucket increment may diverge if bucket boundaries mismatch dynamic distribution; need validation harness.
- Memory overhead of dual queues vs single queue with priority tagging (perf trade-off).
- Shedding policy fairness (could starve non-hot metrics under sustained overload).

## Implementation Order Recommendation
1. Adaptive sizing (low risk, pure math + existing synchronous model) – PARTIAL COMPLETE
2. Async worker (introduce thread + graceful shutdown + fallback path)
3. Flush metrics instrumentation (duration, size, adaptive target)
4. Histogram trial mode (shadow raw path + deviation metrics) before enabling
5. Priority queues + backpressure events
6. Shedding & safeguards

---
Prepared for integration into roadmap (`grafna.md`) once Phase P1 merged.
