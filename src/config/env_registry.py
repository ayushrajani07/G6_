#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from re import Pattern
from typing import Any, Generic, TypeVar

T = TypeVar('T')


class EnvVarType(Enum):
    STRING = auto()
    INTEGER = auto()
    FLOAT = auto()
    BOOLEAN = auto()
    LIST = auto()
    DICT = auto()


@dataclass
class EnvVarDefinition(Generic[T]):
    name: str
    config_path: list[str]
    var_type: EnvVarType
    description: str
    default: T | None = None
    required: bool = False
    choices: list[T] | None = None
    min_value: int | float | None = None
    max_value: int | float | None = None
    pattern: str | Pattern[str] | None = None
    case_sensitive: bool = False
    hidden: bool = False
    deprecated: bool = False
    replacement: str | None = None
    transform: Callable[[str], T] | None = None


class EnvironmentRegistry:
    def __init__(self) -> None:
        self._prefix = "G6_"
        self._defs: dict[str, EnvVarDefinition[Any]] = {}

    def register(self, definition: EnvVarDefinition[Any]) -> None:
        key = definition.name if definition.case_sensitive else definition.name.upper()
        self._defs[key] = definition

    def register_many(self, defs: list[EnvVarDefinition[Any]]) -> None:
        for d in defs:
            self.register(d)

    def get_definition(self, name_without_prefix: str) -> EnvVarDefinition[Any] | None:
        # Exact (case-sensitive) first
        if name_without_prefix in self._defs and self._defs[name_without_prefix].case_sensitive:
            return self._defs[name_without_prefix]
        # Case-insensitive
        return self._defs.get(name_without_prefix.upper())

    def apply_to_config(self, cfg: dict[str, Any]) -> dict[str, Any]:
        out = dict(cfg)
        processed: set[str] = set()
        # First pass: registered vars with validation
        for env_name, env_val in os.environ.items():
            if not env_name.startswith(self._prefix):
                continue
            name_wo = env_name[len(self._prefix):]

            d = self.get_definition(name_wo)
            if not d:
                continue
            processed.add(env_name)
            val = self._convert_value(env_val, d)
            self._set_nested(out, d.config_path, val)

        # Second pass: unregistered legacy heuristic mapping
        for env_name, env_val in os.environ.items():
            if not env_name.startswith(self._prefix) or env_name in processed:
                continue
            parts = env_name[len(self._prefix):].lower().split('_')
            cur = out
            for i, p in enumerate(parts):
                if i == len(parts) - 1:
                    cur[p] = self._convert_value_heuristic(env_val)
                else:
                    nxt = cur.get(p)
                    if not isinstance(nxt, dict):
                        nxt = {}
                        cur[p] = nxt
                    cur = nxt
        return out

    def _set_nested(self, cfg: dict[str, Any], path: list[str], val: Any) -> None:
        cur = cfg
        for i, k in enumerate(path):
            if i == len(path) - 1:
                cur[k] = val
            else:
                nxt = cur.get(k)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[k] = nxt
                cur = nxt

    def _convert_value(self, value: str, d: EnvVarDefinition[Any]) -> Any:
        if d.transform:
            return d.transform(value)
        res: Any
        if d.var_type == EnvVarType.STRING:
            res = value
            if d.pattern:
                pat: Pattern[str] = d.pattern if isinstance(d.pattern, re.Pattern) else re.compile(str(d.pattern))
                if not pat.match(res):
                    pat_str = getattr(pat, 'pattern', str(pat))
                    raise ValueError(f"{d.name} does not match pattern {pat_str}")
        elif d.var_type == EnvVarType.INTEGER:
            res = int(value)
            if d.min_value is not None and res < d.min_value:  # type: ignore[operator]
                raise ValueError(f"{d.name} below min {d.min_value}")
            if d.max_value is not None and res > d.max_value:  # type: ignore[operator]
                raise ValueError(f"{d.name} above max {d.max_value}")
        elif d.var_type == EnvVarType.FLOAT:
            res = float(value)
            if d.min_value is not None and res < d.min_value:  # type: ignore[operator]
                raise ValueError(f"{d.name} below min {d.min_value}")
            if d.max_value is not None and res > d.max_value:  # type: ignore[operator]
                raise ValueError(f"{d.name} above max {d.max_value}")
        elif d.var_type == EnvVarType.BOOLEAN:
            lv = value.strip().lower()
            if lv in ("1","true","yes","on","t","y"):
                res = True
            elif lv in ("0","false","no","off","f","n"):
                res = False
            else:
                raise ValueError(f"{d.name} invalid boolean: {value}")
        elif d.var_type == EnvVarType.LIST:
            res = [s.strip() for s in value.split(',')] if value else []
        elif d.var_type == EnvVarType.DICT:
            tmp: dict[str, str] = {}
            if value:
                for pair in value.split(','):
                    if '=' not in pair:
                        raise ValueError(f"{d.name} invalid pair '{pair}'")
                    k, v = pair.split('=', 1)
                    tmp[k.strip()] = v.strip()
            res = tmp
        else:
            res = value
        if d.choices is not None and res not in d.choices:
            raise ValueError(f"{d.name} must be one of {d.choices}")
        return res

    def _convert_value_heuristic(self, value: str) -> Any:
        s = value.strip()
        low = s.lower()
        if low in ("1","true","yes","on","t","y"):
            return True
        if low in ("0","false","no","off","f","n"):
            return False
        if s.isdigit():
            return int(s)
        try:
            if '.' in s:
                return float(s)
        except Exception:
            pass
        if ',' in s:
            return [p.strip() for p in s.split(',')]
        return s

    def get_documented_variables(self) -> list[EnvVarDefinition[Any]]:
        return [d for d in self._defs.values() if not d.hidden]


registry = EnvironmentRegistry()


def register_common_variables() -> None:
    registry.register_many([
        EnvVarDefinition(name="COLLECTION_INTERVAL", config_path=["collection", "interval_seconds"], var_type=EnvVarType.INTEGER, description="Collection interval (seconds)", min_value=1, max_value=3600),
        EnvVarDefinition(name="STORAGE_CSV_DIR", config_path=["storage", "csv_dir"], var_type=EnvVarType.STRING, description="CSV data directory"),
        EnvVarDefinition(name="STORAGE_INFLUX_ENABLED", config_path=["storage", "influx", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable InfluxDB", default=False),
        EnvVarDefinition(name="STORAGE_INFLUX_URL", config_path=["storage", "influx", "url"], var_type=EnvVarType.STRING, description="Influx URL"),
        EnvVarDefinition(name="STORAGE_INFLUX_TOKEN", config_path=["storage", "influx", "token"], var_type=EnvVarType.STRING, description="Influx token", hidden=True),
        EnvVarDefinition(name="STORAGE_INFLUX_ORG", config_path=["storage", "influx", "org"], var_type=EnvVarType.STRING, description="Influx org"),
        EnvVarDefinition(name="STORAGE_INFLUX_BUCKET", config_path=["storage", "influx", "bucket"], var_type=EnvVarType.STRING, description="Influx bucket"),
        EnvVarDefinition(name="HEALTH_API_ENABLED", config_path=["health", "api", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable health API", default=False),
        EnvVarDefinition(name="HEALTH_API_PORT", config_path=["health", "api", "port"], var_type=EnvVarType.INTEGER, description="Health API port", min_value=1024, max_value=65535),
        EnvVarDefinition(name="METRICS_ENABLED", config_path=["metrics", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable metrics", default=True),
        EnvVarDefinition(name="METRICS_PORT", config_path=["metrics", "port"], var_type=EnvVarType.INTEGER, description="Metrics port", min_value=1024, max_value=65535),
        EnvVarDefinition(name="FEATURES_LIVE_PANEL", config_path=["console", "live_panel"], var_type=EnvVarType.BOOLEAN, description="Console live panel", default=False),
        EnvVarDefinition(name="FEATURES_FANCY_STARTUP", config_path=["console", "fancy_startup"], var_type=EnvVarType.BOOLEAN, description="Fancy startup banner", default=False),
        EnvVarDefinition(name="FEATURES_ANALYTICS_STARTUP", config_path=["features", "analytics_startup"], var_type=EnvVarType.BOOLEAN, description="Analytics at startup", default=False),
        # Circuit metrics exporter
        EnvVarDefinition(name="CIRCUIT_METRICS", config_path=["resilience", "circuit_metrics", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable circuit metrics exporter", default=False),
        EnvVarDefinition(name="CIRCUIT_METRICS_INTERVAL", config_path=["resilience", "circuit_metrics", "interval"], var_type=EnvVarType.FLOAT, description="Circuit metrics export interval (seconds)", min_value=1.0, max_value=3600.0),
        # Health & Prometheus
        EnvVarDefinition(name="HEALTH_PROMETHEUS", config_path=["health", "prometheus", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable health metrics exporter", default=False),
        EnvVarDefinition(name="HEALTH_API_HOST", config_path=["health", "api", "host"], var_type=EnvVarType.STRING, description="Health API bind host", pattern=r"^\S+$"),
        # Alerts subsystem
        EnvVarDefinition(name="ALERTS", config_path=["health", "alerts", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable alerts subsystem", default=False),
        EnvVarDefinition(name="ALERTS_STATE_DIR", config_path=["health", "alerts", "state_directory"], var_type=EnvVarType.STRING, description="Alerts state directory"),
        # Providers resiliency (adaptive circuit breakers on providers)
        EnvVarDefinition(name="ADAPTIVE_CB_PROVIDERS", config_path=["resilience", "adaptive_providers", "enabled"], var_type=EnvVarType.BOOLEAN, description="Wrap providers with adaptive circuit breakers", default=False),
    # Providers retries (standardized tenacity-based)
    EnvVarDefinition(name="RETRY_PROVIDERS", config_path=["resilience", "retry_providers", "enabled"], var_type=EnvVarType.BOOLEAN, description="Compose standardized retries around provider calls", default=False),
    # Influx write path adaptive CB
    EnvVarDefinition(name="ADAPTIVE_CB_INFLUX", config_path=["resilience", "adaptive_influx", "enabled"], var_type=EnvVarType.BOOLEAN, description="Wrap Influx writes with adaptive circuit breaker", default=False),
    # Health components toggle for graded health updates
    EnvVarDefinition(name="HEALTH_COMPONENTS", config_path=["health", "components", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable per-component health updates", default=False),
    # Adaptive CB defaults
    EnvVarDefinition(name="CB_FAILURES", config_path=["resilience", "cb_defaults", "failures"], var_type=EnvVarType.INTEGER, description="Adaptive CB failure threshold", default=5, min_value=1, max_value=1000),
    EnvVarDefinition(name="CB_MIN_RESET", config_path=["resilience", "cb_defaults", "min_reset"], var_type=EnvVarType.FLOAT, description="Adaptive CB min reset timeout (s)", default=10.0, min_value=0.1, max_value=3600.0),
    EnvVarDefinition(name="CB_MAX_RESET", config_path=["resilience", "cb_defaults", "max_reset"], var_type=EnvVarType.FLOAT, description="Adaptive CB max reset timeout (s)", default=300.0, min_value=1.0, max_value=86400.0),
    EnvVarDefinition(name="CB_BACKOFF", config_path=["resilience", "cb_defaults", "backoff"], var_type=EnvVarType.FLOAT, description="Adaptive CB backoff factor", default=2.0, min_value=1.0, max_value=10.0),
    EnvVarDefinition(name="CB_JITTER", config_path=["resilience", "cb_defaults", "jitter"], var_type=EnvVarType.FLOAT, description="Adaptive CB jitter (0..1)", default=0.2, min_value=0.0, max_value=1.0),
    EnvVarDefinition(name="CB_HALF_OPEN_SUCC", config_path=["resilience", "cb_defaults", "half_open_successes"], var_type=EnvVarType.INTEGER, description="Adaptive CB required successes in HALF_OPEN", default=1, min_value=1, max_value=100),
    EnvVarDefinition(name="CB_STATE_DIR", config_path=["resilience", "cb_defaults", "state_dir"], var_type=EnvVarType.STRING, description="Adaptive CB persistence directory"),
    # Retry knobs
    EnvVarDefinition(name="RETRY_MAX_ATTEMPTS", config_path=["resilience", "retry", "max_attempts"], var_type=EnvVarType.INTEGER, description="Retry max attempts", default=3, min_value=1, max_value=100),
    EnvVarDefinition(name="RETRY_MAX_SECONDS", config_path=["resilience", "retry", "max_seconds"], var_type=EnvVarType.FLOAT, description="Retry overall time cap (s)", default=8.0, min_value=0.1, max_value=3600.0),
    EnvVarDefinition(name="RETRY_BACKOFF", config_path=["resilience", "retry", "backoff"], var_type=EnvVarType.FLOAT, description="Retry base backoff (s)", default=0.2, min_value=0.01, max_value=60.0),
    EnvVarDefinition(name="RETRY_JITTER", config_path=["resilience", "retry", "jitter"], var_type=EnvVarType.BOOLEAN, description="Retry add jitter", default=True),
    EnvVarDefinition(name="RETRY_WHITELIST", config_path=["resilience", "retry", "whitelist"], var_type=EnvVarType.STRING, description="Retry exception whitelist (CSV of class names)"),
    EnvVarDefinition(name="RETRY_BLACKLIST", config_path=["resilience", "retry", "blacklist"], var_type=EnvVarType.STRING, description="Retry exception blacklist (CSV of class names)"),
        # Panels / summary bridge toggles (documentation; may be consumed by scripts)
        EnvVarDefinition(name="SUMMARY_PANELS_MODE", config_path=["console", "summary_panels_mode"], var_type=EnvVarType.STRING, description="Summary panels mode toggle", choices=["on","off"]),
        EnvVarDefinition(name="PANELS_DIR", config_path=["console", "panels_dir"], var_type=EnvVarType.STRING, description="Panels directory for bridge"),
        # Phase 10: alert taxonomy expansion / diagnostics
        EnvVarDefinition(name="ALERT_TAXONOMY_EXTENDED", config_path=["alerts", "taxonomy", "extended"], var_type=EnvVarType.BOOLEAN, description="Enable extended alert taxonomy categories (liquidity_low, stale_quote, wide_spread)", default=False),
        EnvVarDefinition(name="ALERT_LIQUIDITY_MIN_RATIO", config_path=["alerts", "taxonomy", "liquidity_min_ratio"], var_type=EnvVarType.FLOAT, description="Min avg volume per option ratio to avoid liquidity_low alert", default=0.05, min_value=0.0, max_value=10.0),
        EnvVarDefinition(name="ALERT_QUOTE_STALE_AGE_S", config_path=["alerts", "taxonomy", "quote_stale_age_s"], var_type=EnvVarType.FLOAT, description="Age in seconds beyond which quotes considered stale", default=45.0, min_value=1.0, max_value=3600.0),
        EnvVarDefinition(name="ALERT_WIDE_SPREAD_PCT", config_path=["alerts", "taxonomy", "wide_spread_pct"], var_type=EnvVarType.FLOAT, description="Spread percentage threshold for wide_spread alert", default=5.0, min_value=0.1, max_value=100.0),
        EnvVarDefinition(name="PIPELINE_INCLUDE_DIAGNOSTICS", config_path=["pipeline", "include_diagnostics"], var_type=EnvVarType.BOOLEAN, description="Include diagnostics block (latency & provider stats) in pipeline result", default=False),
        # Existing (previously undocumented) alert coverage thresholds & compatibility
        EnvVarDefinition(name="ALERT_STRIKE_COV_MIN", config_path=["alerts", "coverage", "strike_min"], var_type=EnvVarType.FLOAT, description="Minimum strike coverage ratio for low_strike_coverage alert", default=0.6, min_value=0.0, max_value=1.0),
        EnvVarDefinition(name="ALERT_FIELD_COV_MIN", config_path=["alerts", "coverage", "field_min"], var_type=EnvVarType.FLOAT, description="Minimum field coverage ratio for low_field_coverage alert", default=0.5, min_value=0.0, max_value=1.0),
        EnvVarDefinition(name="ALERTS_FLAT_COMPAT", config_path=["alerts", "flat_compat"], var_type=EnvVarType.BOOLEAN, description="Export legacy flat alert_* fields alongside nested alerts block", default=True),
        # Strike cache & enrichment async flags
        EnvVarDefinition(name="DISABLE_STRIKE_CACHE", config_path=["strikes", "cache", "disabled"], var_type=EnvVarType.BOOLEAN, description="Disable strike universe cache layer", default=False),
        EnvVarDefinition(name="ENRICH_ASYNC", config_path=["enrichment", "async", "enabled"], var_type=EnvVarType.BOOLEAN, description="Enable async enrichment path", default=False),
        EnvVarDefinition(name="ENRICH_ASYNC_BATCH", config_path=["enrichment", "async", "batch_size"], var_type=EnvVarType.INTEGER, description="Async enrichment batch size", default=50, min_value=1, max_value=5000),
        # Async enrichment tuning (timeouts / workers)
        EnvVarDefinition(name="ENRICH_ASYNC_WORKERS", config_path=["enrichment", "async", "workers"], var_type=EnvVarType.INTEGER, description="Max worker threads for async enrichment", default=4, min_value=1, max_value=128),
        EnvVarDefinition(name="ENRICH_ASYNC_TIMEOUT_MS", config_path=["enrichment", "async", "timeout_ms"], var_type=EnvVarType.INTEGER, description="Timeout (ms) for async enrichment batch completion before fallback", default=3000, min_value=100, max_value=60000),
        # Pipeline rollout gating
        EnvVarDefinition(name="PIPELINE_ROLLOUT", config_path=["pipeline", "rollout", "mode"], var_type=EnvVarType.STRING, description="Pipeline rollout mode (legacy | shadow | primary)", choices=["legacy","shadow","primary"], default="legacy"),
        # Parity float comparison tolerances
        EnvVarDefinition(name="PARITY_FLOAT_RTOL", config_path=["parity", "float", "rtol"], var_type=EnvVarType.FLOAT, description="Relative tolerance for float parity diffs", default=1e-6, min_value=0.0, max_value=1.0),
        EnvVarDefinition(name="PARITY_FLOAT_ATOL", config_path=["parity", "float", "atol"], var_type=EnvVarType.FLOAT, description="Absolute tolerance for float parity diffs", default=1e-9, min_value=0.0, max_value=1.0),
        # Adaptive strike policy (v2)
        EnvVarDefinition(name="STRIKE_POLICY", config_path=["strikes", "policy", "mode"], var_type=EnvVarType.STRING, description="Strike policy mode (fixed | adaptive_v2)", choices=["fixed","adaptive_v2"], default="fixed"),
        EnvVarDefinition(name="STRIKE_POLICY_TARGET", config_path=["strikes", "policy", "adaptive", "target"], var_type=EnvVarType.FLOAT, description="Adaptive strike policy target coverage ratio", default=0.85, min_value=0.1, max_value=1.0),
        EnvVarDefinition(name="STRIKE_POLICY_STEP", config_path=["strikes", "policy", "adaptive", "step"], var_type=EnvVarType.INTEGER, description="Adaptive strike policy step increment for widening/narrowing", default=2, min_value=1, max_value=100),
        EnvVarDefinition(name="STRIKE_POLICY_COOLDOWN", config_path=["strikes", "policy", "adaptive", "cooldown"], var_type=EnvVarType.INTEGER, description="Min cycles between adaptive strike adjustments", default=2, min_value=1, max_value=1000),
        EnvVarDefinition(name="STRIKE_POLICY_WINDOW", config_path=["strikes", "policy", "adaptive", "window"], var_type=EnvVarType.INTEGER, description="Window size (cycles) for recent coverage computation", default=5, min_value=1, max_value=1000),
        EnvVarDefinition(name="STRIKE_POLICY_MAX_ITM", config_path=["strikes", "policy", "adaptive", "max_itm"], var_type=EnvVarType.INTEGER, description="Max allowed ITM strikes span for adaptive policy (baseline + N)", min_value=0, max_value=10000),
        EnvVarDefinition(name="STRIKE_POLICY_MAX_OTM", config_path=["strikes", "policy", "adaptive", "max_otm"], var_type=EnvVarType.INTEGER, description="Max allowed OTM strikes span for adaptive policy (baseline + N)", min_value=0, max_value=10000),
        # Strike universe cache capacity (LRU)
        EnvVarDefinition(name="STRIKE_UNIVERSE_CACHE_SIZE", config_path=["strikes", "cache", "capacity"], var_type=EnvVarType.INTEGER, description="LRU capacity for strike universe cache (entries)", default=256, min_value=0, max_value=100000),
    ])


register_common_variables()

__all__ = [
    "EnvVarType",
    "EnvVarDefinition",
    "EnvironmentRegistry",
    "registry",
]
