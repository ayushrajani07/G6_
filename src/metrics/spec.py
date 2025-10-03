"""Declarative metric specification layer.

This module defines a lightweight structured representation for core
metrics that were previously registered inline in metrics.py. The aim is
to improve discoverability, support automated documentation, and reduce
duplication / drift risk. Only a safe starter subset of metrics is
ported initially; further migration can be incremental.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Callable, Any, List, Optional

from prometheus_client import Gauge, Counter, Histogram, Summary  # type: ignore

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
    predicate: Optional[Callable[[Any], bool]] = None  # Called with registry; if returns False registration skipped

    def register(self, registry):  # pragma: no cover - thin wrapper
        if self.predicate is not None:
            try:
                if not self.predicate(registry):
                    return None
            except Exception:
                return None
        if hasattr(registry, self.attr):
            return getattr(registry, self.attr)
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
            setattr(registry, self.attr, metric)
            if self.group:
                try:
                    registry._metric_groups[self.attr] = self.group.value  # type: ignore[attr-defined]
                except Exception:
                    pass
        return metric


# Starter subset: provider mode, deprecated config keys, index gauges & collection basics
METRIC_SPECS: List[MetricDef] = [
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
# adaptive, cache/perf_cache, panels_integrity). Environment gated metrics
# (e.g. vol surface per-expiry, quality_score) remain dynamically gated and are
# therefore NOT included here yet to avoid altering lazy semantics. They can be
# migrated later with an optional predicate hook in MetricDef if desired.

GROUPED_METRIC_SPECS: List[MetricDef] = [
    # panel_diff group
    MetricDef(
        attr="panel_diff_writes",
        name="g6_panel_diff_writes_total",
        doc="Panel diff snapshots written",
        kind=Counter,
        labels=["type"],
        group=MetricGroup.PANEL_DIFF if hasattr(MetricGroup, 'PANEL_DIFF') else None,  # fallback in case enum lags
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('panel_diff'),
    ),
    MetricDef(
        attr="panel_diff_truncated",
        name="g6_panel_diff_truncated_total",
        doc="Panel diff truncation events",
        kind=Counter,
        labels=["reason"],
        group=MetricGroup.PANEL_DIFF if hasattr(MetricGroup, 'PANEL_DIFF') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('panel_diff'),
    ),
    MetricDef(
        attr="panel_diff_bytes_total",
        name="g6_panel_diff_bytes_total",
        doc="Total bytes of diff JSON written",
        kind=Counter,
        labels=["type"],
        group=MetricGroup.PANEL_DIFF if hasattr(MetricGroup, 'PANEL_DIFF') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('panel_diff'),
    ),
    MetricDef(
        attr="panel_diff_bytes_last",
        name="g6_panel_diff_bytes_last",
        doc="Bytes of last diff JSON written",
        kind=Gauge,
        labels=["type"],
        group=MetricGroup.PANEL_DIFF if hasattr(MetricGroup, 'PANEL_DIFF') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('panel_diff'),
    ),
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
    # perf_cache group (root symbol cache performance)
    MetricDef(
        attr="root_cache_hits",
        name="g6_root_cache_hits",
        doc="Root symbol cache hits",
        kind=Counter,
        group=MetricGroup.PERF_CACHE if hasattr(MetricGroup, 'PERF_CACHE') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('perf_cache'),
    ),
    MetricDef(
        attr="root_cache_misses",
        name="g6_root_cache_misses",
        doc="Root symbol cache misses",
        kind=Counter,
        group=MetricGroup.PERF_CACHE if hasattr(MetricGroup, 'PERF_CACHE') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('perf_cache'),
    ),
    MetricDef(
        attr="root_cache_evictions",
        name="g6_root_cache_evictions",
        doc="Root symbol cache evictions",
        kind=Counter,
        group=MetricGroup.PERF_CACHE if hasattr(MetricGroup, 'PERF_CACHE') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('perf_cache'),
    ),
    MetricDef(
        attr="root_cache_size",
        name="g6_root_cache_size",
        doc="Current root symbol cache size",
        kind=Gauge,
        group=MetricGroup.PERF_CACHE if hasattr(MetricGroup, 'PERF_CACHE') else None,
        predicate=lambda reg: getattr(reg, '_group_allowed', lambda g: True)('perf_cache'),
    ),
    MetricDef(
        attr="root_cache_hit_ratio",
        name="g6_root_cache_hit_ratio",
        doc="Root symbol cache hit ratio (0-1)",
        kind=Gauge,
        group=MetricGroup.PERF_CACHE if hasattr(MetricGroup, 'PERF_CACHE') else None,
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
        # Restore original flag gating: only register when group allowed AND per-expiry flag enabled
        predicate=lambda reg: (getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface') and __import__('os').getenv('G6_VOL_SURFACE_PER_EXPIRY') == '1'),
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
        predicate=lambda reg: (getattr(reg, '_group_allowed', lambda g: True)('analytics_vol_surface') and __import__('os').getenv('G6_VOL_SURFACE') == '1'),
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
]

__all__ = ["MetricDef", "METRIC_SPECS", "GROUPED_METRIC_SPECS"]
