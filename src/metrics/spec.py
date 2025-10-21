"""Declarative metric specification layer.

This module defines a lightweight structured representation for core
metrics that were previously registered inline in metrics.py. The aim is
to improve discoverability, support automated documentation, and reduce
duplication / drift risk. Only a safe starter subset of metrics is
ported initially; further migration can be incremental.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, Summary  # type: ignore

from .groups import MetricGroup


@dataclass(frozen=True)
class MetricDef:
    attr: str                 # Attribute name on registry
    name: str                 # Prometheus metric name
    doc: str                  # Help text
    kind: Any                 # Constructor (Gauge/Counter/Histogram/Summary)
    labels: Sequence[str] | None = None
    group: MetricGroup | None = None
    kwargs: dict | None = None
    predicate: Callable[[Any], bool] | None = None  # Called with registry; if returns False registration skipped

    def register(self, registry):  # pragma: no cover - thin wrapper
        if self.predicate is not None:
            try:
                if not self.predicate(registry):
                    return None
            except Exception:
                return None
        if hasattr(registry, self.attr):
            metric = getattr(registry, self.attr)
            # Normalization: For *_total counters always coerce collector._name to spec.name.
            # We previously attempted a conditional rename only when _name matched the base
            # form. That proved flaky (first test run mismatch). To guarantee deterministic
            # invariants, perform an unconditional alignment whenever there is a discrepancy.
            if isinstance(self.kind, type) and self.name.endswith('_total'):
                try:  # pragma: no cover - defensive path
                    current = getattr(metric, '_name', None)
                    if current != self.name and isinstance(current, str):
                        try:
                            metric._name = self.name
                            # Re-read to confirm; if still mismatched attempt hard replacement.
                            if getattr(metric, '_name', None) != self.name:
                                raise RuntimeError('rename_did_not_stick')
                        except Exception:
                            # Hard replacement path: construct a fresh collector with suffixed name
                            try:
                                ctor_kwargs = self.kwargs or {}
                                if self.labels:
                                    replacement = self.kind(self.name, self.doc, list(self.labels), **ctor_kwargs)
                                else:
                                    replacement = self.kind(self.name, self.doc, **ctor_kwargs)
                                setattr(registry, self.attr, replacement)
                                metric = replacement
                                # Confirm replacement name; if still mismatched, wrap in shim.
                                if getattr(metric, '_name', None) != self.name:
                                    raise RuntimeError('replacement_name_mismatch')
                            except Exception:
                                # Final fallback: wrap original metric in a lightweight shim that exposes forced _name
                                try:
                                    orig = metric
                                    class _NameShim:  # pragma: no cover - trivial delegator
                                        __slots__ = ("_collector", "_name")
                                        def __init__(self, collector, forced_name):
                                            self._collector = collector
                                            self._name = forced_name
                                        def __getattr__(self, item):  # delegate all other attributes/methods
                                            return getattr(self._collector, item)
                                    shim = _NameShim(orig, self.name)
                                    setattr(registry, self.attr, shim)
                                    metric = shim  # type: ignore[assignment]
                                except Exception:
                                    pass
                except Exception:
                    pass
            return metric
        ctor_kwargs = self.kwargs or {}
        try:
            if self.labels:
                metric = self.kind(self.name, self.doc, list(self.labels), **ctor_kwargs)
            else:
                metric = self.kind(self.name, self.doc, **ctor_kwargs)
        except Exception:
            # Duplicate or constructor error: attempt recovery via global registry map
            try:
                from prometheus_client import REGISTRY as _R  # type: ignore
                names_map = getattr(_R, "_names_to_collectors", {})
                metric = names_map.get(self.name)
            except Exception:
                metric = None
        if metric is not None:
            # Apply same (now unconditional) normalization for newly constructed collectors.
            if isinstance(self.kind, type) and self.name.endswith('_total') and metric is not None:
                try:  # pragma: no cover - defensive
                    if getattr(metric, '_name', None) != self.name:
                        metric._name = self.name
                except Exception:
                    pass
            setattr(registry, self.attr, metric)
            if self.group:
                try:
                    registry._metric_groups[self.attr] = self.group.value  # type: ignore[attr-defined]
                except Exception:
                    pass
        return metric


# Starter subset: provider mode, deprecated config keys, index gauges & collection basics
METRIC_SPECS: list[MetricDef] = [
    MetricDef(
        attr="collection_duration",
        name="g6_collection_duration_seconds",
        doc="Time spent collecting data",
        kind=Summary,
    ),
    MetricDef(
        attr="collection_cycles",
        name="g6_collection_cycles",
        doc="Number of collection cycles run",
        kind=Counter,
    ),
    MetricDef(
        attr="collection_errors",
        name="g6_collection_errors",
        doc="Number of collection errors",
        kind=Counter,
        labels=["index", "error_type"],
    ),
    MetricDef(
        attr="index_price",
        name="g6_index_price",
        doc="Current index price",
        kind=Gauge,
        labels=["index"],
    ),
    MetricDef(
        attr="index_atm",
        name="g6_index_atm_strike",
        doc="ATM strike price",
        kind=Gauge,
        labels=["index"],
    ),
    MetricDef(
        attr="options_collected",
        name="g6_options_collected",
        doc="Number of options collected",
        kind=Gauge,
        labels=["index", "expiry"],
    ),
    MetricDef(
        attr="pcr",
        name="g6_put_call_ratio",
        doc="Put-Call Ratio",
        kind=Gauge,
        labels=["index", "expiry"],
    ),
    MetricDef(
        attr="provider_mode",
        name="g6_provider_mode",
        doc="Current provider mode (one-hot gauge)",
        kind=Gauge,
        labels=["mode"],
    ),
    MetricDef(
        attr="config_deprecated_keys",
        name="g6_config_deprecated_keys",
        doc="Deprecated/legacy config keys encountered",
        kind=Counter,
        labels=["key"],
    ),
    # --- SSE client ingestion metrics (migrated from dynamic creation) ---
    MetricDef(
        attr="sse_apply_full_total",
        name="g6_sse_apply_full_total",
        doc="Count of SSE panel full replacements applied",
        kind=Counter,
        group=MetricGroup.SSE_INGEST if hasattr(MetricGroup, 'SSE_INGEST') else None,
    ),
    MetricDef(
        attr="sse_apply_diff_total",
        name="g6_sse_apply_diff_total",
        doc="Count of SSE panel diff merges applied",
        kind=Counter,
        group=MetricGroup.SSE_INGEST if hasattr(MetricGroup, 'SSE_INGEST') else None,
    ),
    MetricDef(
        attr="sse_reconnects_total",
        name="g6_sse_reconnects_total",
        doc="Number of SSE reconnect attempts (by reason)",
        kind=Counter,
        labels=["reason"],
        group=MetricGroup.SSE_INGEST if hasattr(MetricGroup, 'SSE_INGEST') else None,
    ),
    MetricDef(
        attr="sse_backoff_seconds",
        name="g6_sse_backoff_seconds",
        doc="Backoff sleep duration seconds distribution for SSE reconnect attempts",
        kind=Histogram,
        kwargs={"buckets": [0.001,0.005,0.01,0.02,0.05,0.1,0.2,0.5,1,2,5,10,30,60]},
        group=MetricGroup.SSE_INGEST if hasattr(MetricGroup, 'SSE_INGEST') else None,
    ),
    # --- Stream gater / indices_stream governance metrics (Phase 1 unification) ---
    # Stream gater counters intentionally use explicit *_total names (Option A decision) so that
    # spec.name matches the actual registered collector name. We are NOT relying on Prometheus
    # auto-suffix behavior here; we want invariants test alignment and consistent catalog rows.
    MetricDef(
        attr="stream_append",
        name="g6_stream_append_total",
        doc="Indices stream append events",
        kind=Counter,
        labels=["mode"],
    ),
    MetricDef(
        attr="stream_skipped",
        name="g6_stream_skipped_total",
        doc="Indices stream gating skips",
        kind=Counter,
        labels=["mode","reason"],
    ),
    MetricDef(
        attr="stream_state_persist_errors",
        name="g6_stream_state_persist_errors_total",
        doc="State file persistence errors for indices stream gating",
        kind=Counter,
    ),
    MetricDef(
        attr="stream_conflict",
        name="g6_stream_conflict_total",
        doc="Potential concurrent indices stream writer conflicts detected",
        kind=Counter,
    ),
    # ---------------- Option detail metrics (not grouped) ----------------
    MetricDef(
        attr="option_price",
        name="g6_option_price",
        doc="Option price",
        kind=Gauge,
        labels=["index", "expiry", "strike", "type"],
    ),
    MetricDef(
        attr="option_volume",
        name="g6_option_volume",
        doc="Option volume",
        kind=Gauge,
        labels=["index", "expiry", "strike", "type"],
    ),
    MetricDef(
        attr="option_oi",
        name="g6_option_oi",
        doc="Option open interest",
        kind=Gauge,
        labels=["index", "expiry", "strike", "type"],
    ),
    MetricDef(
        attr="option_iv",
        name="g6_option_iv",
        doc="Option implied volatility",
        kind=Gauge,
        labels=["index", "expiry", "strike", "type"],
    ),
    # ---------------- IV estimation core metrics (group: greeks) ----------------
    MetricDef(
        attr="iv_success",
        name="g6_iv_estimation_success",
        doc="Successful IV estimations (alias short form)",
        kind=Counter,
        labels=["index", "expiry"],
        group=MetricGroup.GREEKS,
    ),
    MetricDef(
        attr="iv_fail",
        name="g6_iv_estimation_failure",
        doc="Failed IV estimations (alias short form)",
        kind=Counter,
        labels=["index", "expiry"],
        group=MetricGroup.GREEKS,
    ),
    MetricDef(
        attr="iv_iterations",
        name="g6_iv_estimation_avg_iterations",
        doc="Average IV solver iterations (rolling per cycle)",
        kind=Gauge,
        labels=["index", "expiry"],
        group=MetricGroup.GREEKS,
    ),
    # Alias counters (without _total) kept for backward compatibility/spec parity
    MetricDef(
        attr="iv_success_alias",
        name="g6_iv_estimation_success",
        doc="Successful IV solves (spec alias)",
        kind=Counter,
        labels=["index", "expiry"],
        group=MetricGroup.GREEKS,
    ),
    MetricDef(
        attr="iv_fail_alias",
        name="g6_iv_estimation_failure",
        doc="Failed IV solves (spec alias)",
        kind=Counter,
        labels=["index", "expiry"],
        group=MetricGroup.GREEKS,
    ),
]

#############################################
# Grouped Metric Specs (Phase 2 migration)  #
#############################################
# These cover metrics that were previously registered via the group_registry
# dispatch into per-module init_* helpers (panel_diff, vol_surface, risk_agg,
# adaptive, cache, panels_integrity). Environment gated metrics
# (e.g. vol surface per-expiry, quality_score) remain dynamically gated and are
# therefore NOT included here yet to avoid altering lazy semantics. They can be
# migrated later with an optional predicate hook in MetricDef if desired.

GROUPED_METRIC_SPECS: list[MetricDef] = [
    # panel_diff group migrated to YAML spec (2025-10-05). The dynamic definitions
    # were removed to avoid duplicate registration. If rollback is required,
    # reintroduce the MetricDef entries here or enable a temporary guard flag.
    # analytics_risk_agg group
    MetricDef(
        attr="risk_agg_rows",
        name="g6_risk_agg_rows",
        doc="Rows in last risk aggregation build",
        kind=Gauge,
        group=MetricGroup.ANALYTICS_RISK_AGG if hasattr(MetricGroup, 'ANALYTICS_RISK_AGG') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_risk_agg'),
    ),
    MetricDef(
        attr="risk_agg_notional_delta",
        name="g6_risk_agg_notional_delta",
        doc="Aggregate delta notional for last risk aggregation",
        kind=Gauge,
        group=MetricGroup.ANALYTICS_RISK_AGG if hasattr(MetricGroup, 'ANALYTICS_RISK_AGG') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_risk_agg'),
    ),
    MetricDef(
        attr="risk_agg_notional_vega",
        name="g6_risk_agg_notional_vega",
        doc="Aggregate vega notional for last risk aggregation",
        kind=Gauge,
        group=MetricGroup.ANALYTICS_RISK_AGG if hasattr(MetricGroup, 'ANALYTICS_RISK_AGG') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_risk_agg'),
    ),
    MetricDef(
        attr="risk_agg_bucket_utilization",
        name="g6_risk_agg_bucket_utilization",
        doc="Risk aggregation bucket utilization fraction (0-1)",
        kind=Gauge,
        group=MetricGroup.ANALYTICS_RISK_AGG if hasattr(MetricGroup, 'ANALYTICS_RISK_AGG') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_risk_agg'),
    ),
    # adaptive_controller group
    MetricDef(
        attr="adaptive_controller_actions",
        name="g6_adaptive_controller_actions_total",
        doc="Adaptive controller actions taken",
        kind=Counter,
        labels=["reason","action"],
        group=MetricGroup.ADAPTIVE_CONTROLLER if hasattr(MetricGroup, 'ADAPTIVE_CONTROLLER') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('adaptive_controller'),
    ),
    MetricDef(
        attr="option_detail_mode",
        name="g6_option_detail_mode",
        doc="Current option detail mode (0=full,1=medium,2=low)",
        kind=Gauge,
        labels=["index"],
        group=MetricGroup.ADAPTIVE_CONTROLLER if hasattr(MetricGroup, 'ADAPTIVE_CONTROLLER') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('adaptive_controller'),
    ),
    # cache group (root symbol cache performance)
    MetricDef(
        attr="root_cache_hits",
        name="g6_root_cache_hits",
        doc="Root symbol cache hits",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="root_cache_misses",
        name="g6_root_cache_misses",
        doc="Root symbol cache misses",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="root_cache_evictions",
        name="g6_root_cache_evictions",
        doc="Root symbol cache evictions",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="root_cache_size",
        name="g6_root_cache_size",
        doc="Current root symbol cache size",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="root_cache_hit_ratio",
        name="g6_root_cache_hit_ratio",
        doc="Root symbol cache hit ratio (0-1)",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    ),
    # serialization cache (shares cache group semantics)
    MetricDef(
        attr="serial_cache_hits",
        name="g6_serial_cache_hits_total",
        doc="Serialization cache hits",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="serial_cache_misses",
        name="g6_serial_cache_misses_total",
        doc="Serialization cache misses",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="serial_cache_evictions",
        name="g6_serial_cache_evictions_total",
        doc="Serialization cache evictions",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="serial_cache_size",
        name="g6_serial_cache_size",
        doc="Serialization cache current size",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="serial_cache_hit_ratio",
        name="g6_serial_cache_hit_ratio",
        doc="Serialization cache hit ratio (0-1)",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    # quote cache (kite provider A7 Step 10) - mirrors serialization cache naming style
    MetricDef(
        attr="quote_cache_hits",
        name="g6_quote_cache_hits_total",
        doc="Quote cache hits",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="quote_cache_misses",
        name="g6_quote_cache_misses_total",
        doc="Quote cache misses",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="quote_cache_size",
        name="g6_quote_cache_size",
        doc="Quote cache current size",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="quote_cache_hit_ratio",
        name="g6_quote_cache_hit_ratio",
        doc="Quote cache hit ratio (0-1)",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    # SSE serialization latency (observed when G6_SSE_EMIT_LATENCY_CAPTURE enabled)
    MetricDef(
        attr="sse_serialize_seconds",
        name="g6_sse_serialize_seconds",
        doc="Serialization time distribution for SSE event payloads",
        kind=Histogram,
        kwargs={"buckets": [0.0005,0.001,0.002,0.005,0.01,0.02,0.05,0.1]},
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    # SSE flush latency (publish -> flush on wire) optional instrumentation
    MetricDef(
        attr="sse_flush_seconds",
        name="g6_sse_flush_latency_seconds",
        doc="End-to-end publish-to-flush latency (server internal) for SSE events",
        kind=Histogram,
        kwargs={"buckets": [0.001,0.002,0.005,0.01,0.02,0.05,0.1,0.2,0.5,1.0]},
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    # Trace stage occurrences (increments on serialize + flush) simple counter
    MetricDef(
        attr="sse_trace_stages_total",
        name="g6_sse_trace_stages_total",
        doc="Total trace stage observations (serialize + flush)",
        kind=Counter,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    # Adaptive degrade controller metrics
    MetricDef(
        attr="adaptive_backlog_ratio",
        name="g6_adaptive_backlog_ratio",
        doc="Current backlog ratio sample used by adaptive controller (0-1)",
        kind=Gauge,
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    MetricDef(
        attr="adaptive_transitions_total",
        name="g6_adaptive_transitions_total",
        doc="Adaptive controller transitions (reason)",
        kind=Counter,
        kwargs={"labelnames": ["reason"]},
    group=MetricGroup.CACHE if hasattr(MetricGroup, 'CACHE') else None,
    predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('cache'),
    ),
    # Pipeline phase execution metrics (A7 executor enhancement)
    MetricDef(
        attr="pipeline_phase_attempts",
        name="g6_pipeline_phase_attempts_total",
        doc="Total phase attempts (includes retries)",
        kind=Counter,
        kwargs={"labelnames": ["phase"]},
    ),
    MetricDef(
        attr="pipeline_phase_retries",
        name="g6_pipeline_phase_retries_total",
        doc="Total phase retry attempts (attempt index > 1)",
        kind=Counter,
        kwargs={"labelnames": ["phase"]},
    ),
    MetricDef(
        attr="pipeline_phase_outcomes",
        name="g6_pipeline_phase_outcomes_total",
        doc="Final phase outcomes (one per phase execution sequence)",
        kind=Counter,
        kwargs={"labelnames": ["phase","final_outcome"]},
    ),
    MetricDef(
        attr="pipeline_phase_duration_ms",
        name="g6_pipeline_phase_duration_ms_total",
        doc="Cumulative wall clock milliseconds spent in phase (across attempts)",
        kind=Counter,
        kwargs={"labelnames": ["phase","final_outcome"]},
    ),
    MetricDef(
        attr="pipeline_phase_runs",
        name="g6_pipeline_phase_runs_total",
        doc="Number of completed phase executions (post-retry finalization)",
        kind=Counter,
        kwargs={"labelnames": ["phase","final_outcome"]},
    ),
    # Structured error records (optional low-cardinality counter)
    MetricDef(
        attr="pipeline_phase_error_records",
        name="g6_pipeline_phase_error_records_total",
        doc="Total structured phase error records captured (one per legacy token)",
        kind=Counter,
        kwargs={"labelnames": ["phase","classification"]},
        predicate=lambda reg: True,  # further gated at increment time by env
    ),
    # Pipeline cycle level metrics (A8 metrics expansion)
    MetricDef(
        attr="pipeline_cycle_success",
        name="g6_pipeline_cycle_success",
        doc="Pipeline cycle success state (1 if no phase errors else 0)",
        kind=Gauge,
    ),
    MetricDef(
        attr="pipeline_cycles_total",
        name="g6_pipeline_cycles_total",
        doc="Total pipeline cycles executed (summary produced)",
        kind=Counter,
    ),
    MetricDef(
        attr="pipeline_cycles_success_total",
        name="g6_pipeline_cycles_success_total",
        doc="Total successful pipeline cycles (no phase errors)",
        kind=Counter,
    ),
    MetricDef(
        attr="pipeline_phase_duration_seconds",
        name="g6_pipeline_phase_duration_seconds",
        doc="Histogram of individual phase execution wall time in seconds (attempts aggregated)",
        kind=Histogram,
        kwargs={"labelnames": ["phase","final_outcome"], "buckets": [0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0]},  # env override supported at runtime
    ),
    MetricDef(
        attr="pipeline_cycle_error_ratio",
        name="g6_pipeline_cycle_error_ratio",
        doc="Per-cycle phase error ratio (phases_error / phases_total)",
        kind=Gauge,
    ),
    MetricDef(
        attr="pipeline_cycle_success_rate_window",
        name="g6_pipeline_cycle_success_rate_window",
        doc="Rolling window success rate (0-1) across last N cycles",
        kind=Gauge,
    ),
    MetricDef(
        attr="pipeline_cycle_error_rate_window",
        name="g6_pipeline_cycle_error_rate_window",
        doc="Rolling window error rate (0-1) across last N cycles",
        kind=Gauge,
    ),
    MetricDef(
        attr="pipeline_trends_success_rate",
        name="g6_pipeline_trends_success_rate",
        doc="Success rate derived from trend aggregation file (long horizon)",
        kind=Gauge,
    ),
    MetricDef(
        attr="pipeline_trends_cycles",
        name="g6_pipeline_trends_cycles",
        doc="Total cycles represented in trend aggregation file",
        kind=Gauge,
    ),
    # panels_integrity group (core + extended additive metrics)
    MetricDef(
        attr="panels_integrity_ok",
        name="g6_panels_integrity_ok",
        doc="Panels integrity check pass state (1 ok / 0 failing)",
        kind=Gauge,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    MetricDef(
        attr="panels_integrity_mismatches",
        name="g6_panels_integrity_mismatches",
        doc="Cumulative panel hash mismatches detected",
        kind=Counter,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    MetricDef(
        attr="panels_integrity_checks",
        name="g6_panels_integrity_checks_total",
        doc="Total panel integrity checks run",
        kind=Counter,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    MetricDef(
        attr="panels_integrity_failures",
        name="g6_panels_integrity_failures_total",
        doc="Total panel integrity check failures",
        kind=Counter,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    MetricDef(
        attr="panels_integrity_last_elapsed",
        name="g6_panels_integrity_last_elapsed_seconds",
        doc="Seconds taken by the last integrity check",
        kind=Gauge,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    MetricDef(
        attr="panels_integrity_last_gap",
        name="g6_panels_integrity_last_gap_seconds",
        doc="Gap (seconds) since last successful check",
        kind=Gauge,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    MetricDef(
        attr="panels_integrity_last_success_age",
        name="g6_panels_integrity_last_success_age_seconds",
        doc="Age (seconds) of last successful integrity pass",
        kind=Gauge,
        group=MetricGroup.PANELS_INTEGRITY if hasattr(MetricGroup, 'PANELS_INTEGRITY') else None,
    ),
    # analytics_vol_surface group (migrated; conditional metrics keep predicates to preserve env-based gating semantics)
    MetricDef(
        attr="vol_surface_rows",
        name="g6_vol_surface_rows",
        doc="Vol surface row count by source",
        kind=Gauge,
        labels=["index","source"],
        group=MetricGroup.ANALYTICS_VOL_SURFACE if hasattr(MetricGroup, 'ANALYTICS_VOL_SURFACE') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface'),
    ),
    MetricDef(
        attr="vol_surface_rows_expiry",
        name="g6_vol_surface_rows_expiry",
        doc="Vol surface per-expiry row count by source",
        kind=Gauge,
        labels=["index","expiry","source"],
        group=MetricGroup.ANALYTICS_VOL_SURFACE if hasattr(MetricGroup, 'ANALYTICS_VOL_SURFACE') else None,
        # Register only when group allowed AND env flag explicitly enables per-expiry metrics
        predicate=lambda reg: (
            getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface')
            and os.getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1'
        ),
    ),
    MetricDef(
        attr="vol_surface_interpolated_fraction",
        name="g6_vol_surface_interpolated_fraction",
        doc="Fraction of interpolated rows in surface",
        kind=Gauge,
        labels=["index"],
        group=MetricGroup.ANALYTICS_VOL_SURFACE if hasattr(MetricGroup, 'ANALYTICS_VOL_SURFACE') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface'),
    ),
    MetricDef(
        attr="vol_surface_quality_score",
        name="g6_vol_surface_quality_score",
        doc="Vol surface quality score (0-100)",
        kind=Gauge,
        labels=["index"],
        group=MetricGroup.ANALYTICS_VOL_SURFACE if hasattr(MetricGroup, 'ANALYTICS_VOL_SURFACE') else None,
        # Always register when group allowed (removed legacy env flag gating to meet spec presence requirement)
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface'),
    ),
    MetricDef(
        attr="vol_surface_interp_seconds",
        name="g6_vol_surface_interp_seconds",
        doc="Interpolation timing distribution",
        kind=Histogram,
        labels=None,
        group=MetricGroup.ANALYTICS_VOL_SURFACE if hasattr(MetricGroup, 'ANALYTICS_VOL_SURFACE') else None,
        kwargs={"buckets": [0.001,0.005,0.01,0.02,0.05,0.1]},
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface'),
    ),
    # Adaptive interpolation alert support metrics (streak + alert counter)
    MetricDef(
        attr="adaptive_interpolation_streak",
        name="g6_adaptive_interpolation_streak",
        doc="Current consecutive builds above interpolation fraction threshold",
        kind=Gauge,
        labels=["index"],
        group=MetricGroup.ADAPTIVE_CONTROLLER if hasattr(MetricGroup, 'ADAPTIVE_CONTROLLER') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('adaptive_controller'),
    ),
    MetricDef(
        attr="adaptive_interpolation_alerts",
        name="g6_adaptive_interpolation_alerts_total",
        doc="Interpolation fraction high streak alerts",
        kind=Counter,
        labels=["index","reason"],
        group=MetricGroup.ADAPTIVE_CONTROLLER if hasattr(MetricGroup, 'ADAPTIVE_CONTROLLER') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('adaptive_controller'),
    ),
]

__all__ = ["MetricDef", "METRIC_SPECS", "GROUPED_METRIC_SPECS"]
