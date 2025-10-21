"""Centralized environment configuration for the Summary / Panels pipeline.

This module consolidates scattered os.getenv lookups into a single, typed
dataclass (`SummaryEnv`) with explicit defaults, normalization, and light
validation.  All new environment-based behavior SHOULD route through this
module; direct os.getenv usage in summary code is to be incrementally
removed (except for highly local / experimental bench scripts).

Design goals:
  * Single source of truth for default values and parsing rules.
  * Explicit bool/int/float coercion with safe fallbacks.
  * Support unified refresh cadence override while preserving per-type knobs.
  * Capture dynamic panel width/height overrides (G6_PANEL_W_*, G6_PANEL_H_*).
  * Surface deprecated env vars encountered (for logging / future removal).

Field naming conventions:
  * Closely match semantic meaning rather than raw env var names.
  * Raw / legacy values (if any) are not re-exposed unless required.

Backward compatibility:
  * Legacy `G6_MASTER_REFRESH_SEC` is honored ONLY when the unified
    `G6_SUMMARY_REFRESH_SEC` is absent.
  * Deprecated or removed variables are intentionally not materialized; if
    encountered they are recorded in `deprecated_seen`.

Planned follow-ups (future phases):
  * Emit a structured diagnostics panel reflecting loaded configuration.
  * Provide a CLI flag to dump effective config as JSON.
  * Enforce deprecation errors after a grace window.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SummaryEnv",
    "load_summary_env",
]


# ---------------------------- Parsing Helpers ---------------------------- #

TRUE_SET = {"1", "true", "yes", "on"}
FALSE_SET = {"0", "false", "no", "off"}


def _get(environ: Mapping[str, str], key: str) -> str | None:  # small shim
    v = environ.get(key)
    if v is None:
        return None
    v2 = v.strip()
    return v2 if v2 != "" else None


def _get_bool(environ: Mapping[str, str], key: str, default: bool = False) -> bool:
    v = _get(environ, key)
    if v is None:
        return default
    lv = v.lower()
    if lv in TRUE_SET:
        return True
    if lv in FALSE_SET:
        return False
    return default  # Unrecognized -> default


def _get_int(
    environ: Mapping[str, str], key: str, default: int, *, min_v: int | None = None, max_v: int | None = None
) -> int:
    v = _get(environ, key)
    if v is None:
        return default
    try:
        iv = int(float(v))  # allow floats like "15.0"
    except ValueError:
        return default
    if min_v is not None and iv < min_v:
        iv = min_v
    if max_v is not None and iv > max_v:
        iv = max_v
    return iv


def _get_float(
    environ: Mapping[str, str], key: str, default: float, *, min_v: float | None = None, max_v: float | None = None
) -> float:
    v = _get(environ, key)
    if v is None:
        return default
    try:
        fv = float(v)
    except ValueError:
        return default
    if min_v is not None and fv < min_v:
        fv = min_v
    if max_v is not None and fv > max_v:
        fv = max_v
    return fv


def _get_list(
    environ: Mapping[str, str], key: str, default: Iterable[str] = (), *, sep: str = ",", lower: bool = False
) -> list[str]:
    v = _get(environ, key)
    if v is None:
        return list(default)
    parts = [p.strip() for p in v.split(sep)]
    if lower:
        parts = [p.lower() for p in parts]
    return [p for p in parts if p]


DEPRECATED_ENV = {
    "G6_SUMMARY_PANELS_MODE",
    "G6_SUMMARY_READ_PANELS",
    "G6_SUMMARY_UNIFIED_SNAPSHOT",
}

PANEL_W_RE = re.compile(r"^G6_PANEL_W_(?P<name>[A-Z0-9_]+)$")
PANEL_H_RE = re.compile(r"^G6_PANEL_H_(?P<name>[A-Z0-9_]+)$")


@dataclass(slots=True)
class SummaryEnv:
    # Cadence / refresh
    refresh_unified_sec: float | None
    refresh_meta_sec: float
    refresh_res_sec: float

    # File / path / panels
    panels_dir: str
    status_file: str

    # HTTP / server toggles
    unified_http_enabled: bool
    unified_http_port: int
    sse_http_enabled: bool
    sse_http_port: int
    metrics_http_enabled: bool
    metrics_http_port: int
    resync_http_port: int | None

    # SSE client (terminal consumer) settings
    client_sse_url: str | None
    client_sse_types: list[str]
    client_sse_timeout_sec: float

    # SSE security / access
    sse_token: str | None
    sse_allow_ips: list[str]
    sse_connect_rate_spec: str | None
    sse_allow_user_agents: list[str]
    sse_allow_origin: str | None

    # Feature flags / modes
    curated_mode: bool
    summary_mode: str | None
    unified_model_init_debug: bool
    plain_diff_enabled: bool
    alt_screen: bool
    auto_full_recovery: bool
    rich_diff_demo_enabled: bool

    # Dossier / snapshot extras
    dossier_path: str | None
    dossier_interval_sec: float

    # Thresholds / performance
    threshold_overrides_raw: str | None
    threshold_overrides: dict[str, Any]
    backoff_badge_window_ms: float
    provider_latency_warn_ms: float
    provider_latency_err_ms: float
    memory_level1_mb: float
    memory_level2_mb: float

    # Output / logging
    output_sinks: list[str]
    indices_panel_log: str | None

    # Panel layout overrides
    panel_clip: int
    panel_auto_fit: bool
    panel_min_col_w: int | None
    panel_w_overrides: dict[str, int] = field(default_factory=dict)
    panel_h_overrides: dict[str, int] = field(default_factory=dict)

    # Deprecated envs encountered (for diagnostics only)
    deprecated_seen: list[str] = field(default_factory=list)

    # Raw metrics URL (for client polling fallback)
    metrics_url: str = "http://127.0.0.1:9108/metrics"

    # Misc / sinks
    output_sinks_raw: str = "stdout,logging"

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> SummaryEnv:  # noqa: C901 (complex but contained)
        deprecated_seen: list[str] = [k for k in environ if k in DEPRECATED_ENV]

        # Capture raw values to drive nuanced fallback semantics expected by tests.
        unified_raw = _get(environ, "G6_SUMMARY_REFRESH_SEC")
        unified_parsed = _get_float(environ, "G6_SUMMARY_REFRESH_SEC", default=-1.0, min_v=0.0)
        unified_valid = unified_parsed >= 0
        if unified_valid:
            unified_refresh: float | None = unified_parsed  # type: ignore
        else:
            legacy_master = _get_float(environ, "G6_MASTER_REFRESH_SEC", default=-1.0, min_v=0.0)
            if legacy_master >= 0:
                unified_refresh = legacy_master  # legacy honored
            else:
                unified_refresh = None  # both missing or invalid

        default_refresh = 15.0
        # Test expectations: if unified is absent OR invalid AND master absent, per-type overrides
        # should NOT apply even if env vars G6_SUMMARY_META_REFRESH_SEC / RES present; defaults=15.
        per_type_override_allowed = isinstance(unified_refresh, float) or (unified_valid and unified_raw is not None)
        if per_type_override_allowed:
            meta_refresh = _get_float(
                environ,
                "G6_SUMMARY_META_REFRESH_SEC",
                default=unified_refresh if isinstance(unified_refresh, float) else default_refresh,
                min_v=1.0,
            )
            res_refresh = _get_float(
                environ,
                "G6_SUMMARY_RES_REFRESH_SEC",
                default=unified_refresh if isinstance(unified_refresh, float) else default_refresh,
                min_v=1.0,
            )
        else:
            # Unified/master both absent or unified invalid with no master fallback -> ignore per-type env values.
            meta_refresh = default_refresh
            res_refresh = default_refresh

        panels_dir = _get(environ, "G6_PANELS_DIR") or os.path.join("data", "panels")
        status_file = (
            _get(environ, "G6_SUMMARY_STATUS_FILE")
            or _get(environ, "G6_STATUS_FILE")
            or "data/runtime_status.json"
        )

        # HTTP toggles
        unified_http_enabled = _get_bool(environ, "G6_UNIFIED_HTTP", False)
        unified_http_port = _get_int(environ, "G6_UNIFIED_HTTP_PORT", 9329, min_v=1)
        sse_http_enabled = _get_bool(environ, "G6_SSE_HTTP", False)
        sse_http_port = _get_int(environ, "G6_SSE_HTTP_PORT", 9320, min_v=1)
        metrics_http_enabled = _get_bool(environ, "G6_SUMMARY_METRICS_HTTP", False)
        metrics_http_port = _get_int(environ, "G6_METRICS_HTTP_PORT", 9325, min_v=1)
        resync_http_port_raw = _get(environ, "G6_RESYNC_HTTP_PORT")
        resync_http_port = None
        if resync_http_port_raw:
            try:
                resync_http_port = int(resync_http_port_raw)
            except ValueError:
                resync_http_port = None

        # SSE client consumption (terminal) & security gating
        client_sse_url = _get(environ, "G6_SUMMARY_SSE_URL")
        client_sse_types = _get_list(environ, "G6_SUMMARY_SSE_TYPES", ["panel_full", "panel_diff"], lower=True)
        client_sse_timeout_sec = _get_float(environ, "G6_SUMMARY_SSE_TIMEOUT", 45.0, min_v=5.0)

        sse_token = _get(environ, "G6_SSE_API_TOKEN")
        sse_allow_ips = _get_list(environ, "G6_SSE_IP_ALLOW", [])
        sse_connect_rate_spec = _get(environ, "G6_SSE_IP_CONNECT_RATE")
        sse_allow_user_agents = _get_list(environ, "G6_SSE_UA_ALLOW", [])
        sse_allow_origin = _get(environ, "G6_SSE_ALLOW_ORIGIN")

        # Feature flags
        curated_mode = _get_bool(environ, "G6_SUMMARY_CURATED_MODE", False)
        summary_mode = (_get(environ, "G6_SUMMARY_MODE") or "").lower() or None
        unified_model_init_debug = _get_bool(environ, "G6_UNIFIED_MODEL_INIT_DEBUG", False)
        plain_diff_enabled = True  # legacy G6_SUMMARY_PLAIN_DIFF removed (always-on diff suppression)
        alt_screen = _get_bool(environ, "G6_SUMMARY_ALT_SCREEN", True)
        auto_full_recovery = _get_bool(environ, "G6_SUMMARY_AUTO_FULL_RECOVERY", True)
        rich_diff_demo_enabled = _get_bool(environ, "G6_SUMMARY_RICH_DIFF", False)

        # Dossier
        dossier_path = _get(environ, "G6_SUMMARY_DOSSIER_PATH")
        dossier_interval_sec = _get_float(environ, "G6_SUMMARY_DOSSIER_INTERVAL_SEC", 5.0, min_v=1.0)

        # Threshold overrides
        threshold_overrides_raw = _get(environ, "G6_SUMMARY_THRESH_OVERRIDES")
        threshold_overrides: dict[str, Any] = {}
        if threshold_overrides_raw:
            try:
                obj = json.loads(threshold_overrides_raw)
                if isinstance(obj, dict):
                    threshold_overrides = obj  # trust as-is
            except Exception:
                pass  # ignore malformed

        backoff_badge_window_ms = _get_float(environ, "G6_SUMMARY_BACKOFF_BADGE_MS", 120000.0, min_v=1000.0)
        provider_latency_warn_ms = _get_float(environ, "G6_PROVIDER_LAT_WARN_MS", 400.0, min_v=1.0)
        provider_latency_err_ms = _get_float(environ, "G6_PROVIDER_LAT_ERR_MS", 800.0, min_v=1.0)
        memory_level1_mb = _get_float(environ, "G6_MEMORY_LEVEL1_MB", 200.0, min_v=1.0)
        memory_level2_mb = _get_float(environ, "G6_MEMORY_LEVEL2_MB", 300.0, min_v=1.0)

        output_sinks_raw = _get(environ, "G6_OUTPUT_SINKS") or "stdout,logging"
        output_sinks = [s for s in (p.strip() for p in output_sinks_raw.split(',')) if s]

        indices_panel_log = _get(environ, "G6_INDICES_PANEL_LOG")

        panel_clip = _get_int(environ, "G6_PANEL_CLIP", 60, min_v=1)
        panel_auto_fit = _get_bool(environ, "G6_PANEL_AUTO_FIT", False)
        panel_min_col_w_env = _get(environ, "G6_PANEL_MIN_COL_W")
        panel_min_col_w: int | None
        if panel_min_col_w_env is not None:
            try:
                panel_min_col_w = max(1, int(float(panel_min_col_w_env)))
            except ValueError:
                panel_min_col_w = None
        else:
            panel_min_col_w = None

        panel_w_overrides: dict[str, int] = {}
        panel_h_overrides: dict[str, int] = {}
        for k, v in environ.items():
            m_w = PANEL_W_RE.match(k)
            if m_w:
                try:
                    panel_w_overrides[m_w.group("name").lower()] = max(1, int(float(v)))
                except ValueError:
                    continue
            m_h = PANEL_H_RE.match(k)
            if m_h:
                try:
                    panel_h_overrides[m_h.group("name").lower()] = max(1, int(float(v)))
                except ValueError:
                    continue

        metrics_url = _get(environ, "G6_METRICS_URL") or "http://127.0.0.1:9108/metrics"

        return cls(
            refresh_unified_sec=unified_refresh if isinstance(unified_refresh, float) else None,
            refresh_meta_sec=meta_refresh,
            refresh_res_sec=res_refresh,
            panels_dir=panels_dir,
            status_file=status_file,
            unified_http_enabled=unified_http_enabled,
            unified_http_port=unified_http_port,
            sse_http_enabled=sse_http_enabled,
            sse_http_port=sse_http_port,
            metrics_http_enabled=metrics_http_enabled,
            metrics_http_port=metrics_http_port,
            resync_http_port=resync_http_port,
            client_sse_url=client_sse_url,
            client_sse_types=client_sse_types,
            client_sse_timeout_sec=client_sse_timeout_sec,
            sse_token=sse_token,
            sse_allow_ips=sse_allow_ips,
            sse_connect_rate_spec=sse_connect_rate_spec,
            sse_allow_user_agents=sse_allow_user_agents,
            sse_allow_origin=sse_allow_origin,
            curated_mode=curated_mode,
            summary_mode=summary_mode,
            unified_model_init_debug=unified_model_init_debug,
            plain_diff_enabled=plain_diff_enabled,
            alt_screen=alt_screen,
            auto_full_recovery=auto_full_recovery,
            rich_diff_demo_enabled=rich_diff_demo_enabled,
            dossier_path=dossier_path,
            dossier_interval_sec=dossier_interval_sec,
            threshold_overrides_raw=threshold_overrides_raw,
            threshold_overrides=threshold_overrides,
            backoff_badge_window_ms=backoff_badge_window_ms,
            provider_latency_warn_ms=provider_latency_warn_ms,
            provider_latency_err_ms=provider_latency_err_ms,
            memory_level1_mb=memory_level1_mb,
            memory_level2_mb=memory_level2_mb,
            output_sinks=output_sinks,
            indices_panel_log=indices_panel_log,
            panel_clip=panel_clip,
            panel_auto_fit=panel_auto_fit,
            panel_min_col_w=panel_min_col_w,
            panel_w_overrides=panel_w_overrides,
            panel_h_overrides=panel_h_overrides,
            deprecated_seen=deprecated_seen,
            metrics_url=metrics_url,
            output_sinks_raw=output_sinks_raw,
        )

    # Convenience helpers -------------------------------------------------- #
    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable summary (safe for diagnostics)."""
        return {
            "refresh_unified_sec": self.refresh_unified_sec,
            "refresh_meta_sec": self.refresh_meta_sec,
            "refresh_res_sec": self.refresh_res_sec,
            "panels_dir": self.panels_dir,
            "status_file": self.status_file,
            "unified_http_enabled": self.unified_http_enabled,
            "sse_http_enabled": self.sse_http_enabled,
            "metrics_http_enabled": self.metrics_http_enabled,
            "resync_http_port": self.resync_http_port,
            "client_sse_url": self.client_sse_url,
            "client_sse_types": self.client_sse_types,
            "curated_mode": self.curated_mode,
            "summary_mode": self.summary_mode,
            "plain_diff_enabled": self.plain_diff_enabled,
            "alt_screen": self.alt_screen,
            "auto_full_recovery": self.auto_full_recovery,
            "dossier_path": self.dossier_path,
            "threshold_override_keys": sorted(self.threshold_overrides.keys()),
            "panel_w_override_keys": sorted(self.panel_w_overrides.keys()),
            "panel_h_override_keys": sorted(self.panel_h_overrides.keys()),
            "deprecated_seen": self.deprecated_seen,
        }


_CACHED: SummaryEnv | None = None


def load_summary_env(*, force_reload: bool = False, environ: Mapping[str, str] | None = None) -> SummaryEnv:
    """Load (and cache) the effective SummaryEnv.

    Pass force_reload=True to rebuild cache (e.g., in tests that monkeypatch
    os.environ). The optional `environ` parameter allows injection of a custom
    mapping (skips global cache if provided explicitly).
    """
    global _CACHED
    if environ is not None:
        # Bypass global cache for explicit mapping usage (test helper scenario).
        return SummaryEnv.from_environ(environ)
    if _CACHED is None or force_reload:
        _CACHED = SummaryEnv.from_environ(os.environ)
    return _CACHED
