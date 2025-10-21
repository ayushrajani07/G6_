"""Bootstrap helpers for initializing RuntimeContext.

This module extracts early initialization concerns from `unified_main.py` to
reduce its size and improve testability.

Current responsibilities:
  * Load config (delegates to `unified_main.load_config` for now to preserve behavior)
  * Initialize metrics server (reuse existing setup_metrics_server)
  * Populate a `RuntimeContext` instance

Future planned responsibilities (see roadmap):
  * Provider factory instantiation & failover wiring
  * Health monitor startup
  * Event bus initialization
  * CSV / Parquet sink setup abstraction
"""
from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from typing import Any

from src.config.runtime_config import get_runtime_config
from src.orchestrator.context import RuntimeContext
from src.utils.build_info import auto_register_build_info

logger = logging.getLogger(__name__)

# Deliberate shallow imports to avoid circular dependencies
# Use Optional[Callable] placeholders to avoid mypy redefinition/assignment errors.
setup_metrics_server: Callable[..., Any] | None = None
try:  # pragma: no cover - optional path if metrics not yet refactored
    from src.metrics import setup_metrics_server as _setup_metrics_server  # facade import
    setup_metrics_server = _setup_metrics_server
except Exception:  # pragma: no cover
    setup_metrics_server = None

# Use canonical config loader (ConfigWrapper) to avoid depending on legacy unified_main.
load_config_fn: Callable[[str], Any] | None = None
try:
    from src.config.loader import load_config as _load_config
    load_config_fn = _load_config
except Exception:  # pragma: no cover
    try:  # fallback to legacy if new path unavailable
        from src.unified_main import load_config as _legacy_load_config
        load_config_fn = _legacy_load_config
    except Exception:
        load_config_fn = None


def run_env_deprecation_scan(*, strict_mode_override: bool | None = None) -> None:
    """Scan environment for deprecated variables and emit warnings / raise if strict.

    Parameters
    ----------
    strict_mode_override : bool | None
        Force strict mode on/off (bypasses env flag) when not None.
    """
    try:
        from src.config.env_lifecycle import ENV_LIFECYCLE_REGISTRY
        from src.utils.env_flags import is_truthy_env
        if strict_mode_override is None:
            strict_mode = is_truthy_env('G6_ENV_DEPRECATION_STRICT')
        else:
            strict_mode = strict_mode_override
        allowlist = set((os.getenv('G6_ENV_DEPRECATION_ALLOW','') or '').split(',')) if os.getenv('G6_ENV_DEPRECATION_ALLOW') else set()
        for _entry in ENV_LIFECYCLE_REGISTRY:
            if _entry.status == 'deprecated' and os.getenv(_entry.name) is not None:
                repl = f" Use {_entry.replacement} instead." if _entry.replacement else ""
                msg = f"[env-deprecated] {_entry.name} is deprecated{repl}"
                if strict_mode and _entry.name not in allowlist:
                    logger.error(msg + " (strict mode violation)")
                    raise RuntimeError(f"Deprecated env var disallowed in strict mode: {_entry.name}")
                else:
                    logger.warning(msg)
    except RuntimeError:
        # Re-raise strict violation immediately
        raise
    except Exception:  # pragma: no cover - non-fatal path
        logger.debug("Env lifecycle deprecation scan failed", exc_info=True)


def bootstrap_runtime(config_path: str,
                      *,
                      reset_metrics: bool = False,
                      custom_registry: bool = False,
                      enable_resource_sampler: bool = True) -> tuple[RuntimeContext, Any | None]:
    """Bootstrap core services and return (context, metrics).

    Parameters
    ----------
    config_path : str
        Path to JSON configuration.
    reset_metrics : bool
        Whether to reset Prometheus default registry before creating metrics.
    custom_registry : bool
        Use a custom CollectorRegistry instead of global registry.
    enable_resource_sampler : bool
        Launch resource sampler thread for utilization gauges.
    """
    if load_config_fn is None:
        raise RuntimeError("load_config unavailable; import order issue")
    raw_cfg = load_config_fn(config_path)

    metrics: Any | None = None
    metrics_stop: Callable[[], None] = (lambda: None)
    if setup_metrics_server is not None:
        try:
            port = getattr(raw_cfg, 'get', lambda *a, **k: None)('metrics.port') if hasattr(raw_cfg, 'get') else None
        except Exception:
            port = None
        try:
            metrics, metrics_stop = setup_metrics_server(
                port=raw_cfg.raw.get('metrics', {}).get('port', 9108) if hasattr(raw_cfg, 'raw') else 9108,
                host=raw_cfg.raw.get('metrics', {}).get('host', '0.0.0.0') if hasattr(raw_cfg, 'raw') else '0.0.0.0',
                enable_resource_sampler=enable_resource_sampler,
                use_custom_registry=custom_registry,
                reset=reset_metrics,
            )
        except Exception:
            logger.exception("Metrics server initialization failed")

    # Build runtime_config snapshot (loop/metrics env) and attach to context
    try:
        rt_cfg = get_runtime_config(refresh=True)
    except Exception:
        rt_cfg = None
    ctx = RuntimeContext(config=raw_cfg, runtime_config=rt_cfg, metrics=metrics)
    # Emit deprecation warnings / strict enforcement
    run_env_deprecation_scan()
    # Auto register build info metric (idempotent). Allows env overrides:
    # G6_VERSION, G6_GIT_COMMIT. Config hash derived from raw config contents.
    try:
        auto_register_build_info(metrics, raw_cfg)
    except Exception:  # pragma: no cover - non-fatal
        logger.debug("Auto build info registration failed", exc_info=True)

    # Component initialization (now default ON). Set G6_DISABLE_COMPONENTS=1 to skip.
    if os.environ.get('G6_DISABLE_COMPONENTS','').lower() not in ('1','true','yes','on'):
        try:
            from src.orchestrator.components import apply_circuit_breakers, init_health, init_providers, init_storage
            providers = init_providers(raw_cfg)
            csv_sink, influx_sink = init_storage(raw_cfg)
            apply_circuit_breakers(raw_cfg, providers)
            health = init_health(raw_cfg, providers, csv_sink, influx_sink)
            ctx.providers = providers
            ctx.csv_sink = csv_sink
            ctx.influx_sink = influx_sink
            ctx.health_monitor = health
        except Exception:
            logger.exception("Component bootstrap (providers/storage/health) failed; proceeding with partial context")
            # If failure likely due to missing credentials and we are in premarket init window, emit guidance.
            try:
                from src.utils.market_hours import get_next_market_open, is_premarket_window
                if is_premarket_window():
                    nxt = get_next_market_open()
                    logger.warning(
                        "Premarket bootstrap partial (credentials missing?). Will retry provider init automatically after regular open at %s if orchestrator restarts, or set credentials earlier to enable warm caches.",
                        nxt
                    )
            except Exception:  # pragma: no cover
                pass
    # Start catalog HTTP server if enabled
    from src.utils.env_flags import is_truthy_env as _is_truthy_env
    if _is_truthy_env('G6_CATALOG_HTTP'):
        try:
            from src.orchestrator.catalog_http import start_http_server_in_thread
            start_http_server_in_thread()
        except Exception:
            logger.exception("Catalog HTTP server failed to start")

    # One-shot orchestrator startup summary (structured + optional human block)
    try:
        if '_G6_ORCH_SUMMARY_EMITTED' not in globals():
            globals()['_G6_ORCH_SUMMARY_EMITTED'] = True
            # Derive key runtime flags / counts
            try:
                loop_interval = getattr(rt_cfg, 'loop_interval', None) or getattr(raw_cfg, 'raw', {}).get('loop', {}).get('interval', None) if hasattr(raw_cfg, 'raw') else None
            except Exception:
                loop_interval = None
            # Indices count: attempt to access planned indices list in config (common key patterns)
            indices_count = None
            indices_sample = None
            try:
                raw_indices = None
                if hasattr(raw_cfg, 'raw'):
                    rc = raw_cfg.raw
                    raw_indices = rc.get('indices') or rc.get('symbols') or rc.get('index_list')
                if isinstance(raw_indices, (list, tuple)):
                    indices_count = len(raw_indices)
                    if raw_indices:
                        head = list(raw_indices)[:3]
                        indices_sample = ','.join(str(x) for x in head)
                        if indices_count > 3:
                            indices_sample += ',...'
            except Exception:
                pass
            # Collector / pipeline flags
            try:
                pipeline_v2 = int(_is_truthy_env('G6_COLLECTOR_PIPELINE_V2'))
            except Exception:
                pipeline_v2 = 0
            diff_mode = int(_is_truthy_env('G6_SSE_STRUCTURED'))
            structured_sse = diff_mode  # alias for clarity
            quiet_mode = int(_is_truthy_env('G6_QUIET_MODE'))
            salvage_enabled = int(_is_truthy_env('G6_FOREIGN_EXPIRY_SALVAGE'))
            domain_models = int(_is_truthy_env('G6_DOMAIN_MODELS'))
            egress_frozen = int(_is_truthy_env('G6_EGRESS_FROZEN'))
            # Provider client presence
            has_provider_client = 0
            try:
                providers = getattr(ctx, 'providers', None)
                if providers:
                    # heuristic: any provider with attribute 'kite' not None
                    for p in (providers if isinstance(providers, (list, tuple, set)) else [providers]):
                        if getattr(p, 'kite', None) is not None:
                            has_provider_client = 1
                            break
            except Exception:
                pass
            # Metrics HTTP server status
            metrics_http = 0
            try:
                if metrics is not None:
                    # Look for internal server thread / port attr heuristics
                    if hasattr(metrics, 'server') or hasattr(metrics, 'port'):
                        metrics_http = 1
            except Exception:
                pass
            # Build info gauge presence heuristic
            build_info_registered = 0
            try:
                from prometheus_client import REGISTRY as _R
                for fam in _R.collect():  # pragma: no cover (iter small)
                    if getattr(fam, 'name', '') == 'g6_build_info':
                        build_info_registered = 1
                        break
            except Exception:
                pass
            # Overrides count from settings snapshot if already loaded
            overrides_count = 0
            try:
                from src.collector.settings import get_collector_settings
                _s = get_collector_settings()
                overrides_count = len(getattr(_s, 'log_level_overrides', {}) or {})
                pipeline_v2 = int(bool(getattr(_s, 'pipeline_v2_flag', False))) or pipeline_v2
                quiet_mode = int(bool(getattr(_s, 'quiet_mode', False))) or quiet_mode
                salvage_enabled = int(bool(getattr(_s, 'salvage_enabled', False))) or salvage_enabled
                domain_models = int(bool(getattr(_s, 'domain_models', False))) or domain_models
            except Exception:
                pass
            start_ts = int(getattr(ctx, 'start_time', time.time()))
            # Human-readable block first (if requested) so tests capturing single call see both
            try:
                from src.utils.env_flags import is_truthy_env
                human_flag = is_truthy_env('G6_ORCH_SUMMARY_HUMAN')
            except Exception:
                human_flag = _is_truthy_env('G6_ORCH_SUMMARY_HUMAN')
            if human_flag:
                try:  # pragma: no cover
                    from src.utils.human_log import emit_human_summary
                    emit_human_summary(
                        'Orchestrator Summary',
                        [
                            ('loop_interval', loop_interval),
                            ('indices_count', indices_count),
                            ('indices_sample', indices_sample),
                            ('pipeline_v2', pipeline_v2),
                            ('diff_mode', diff_mode),
                            ('structured_sse', structured_sse),
                            ('quiet_mode', quiet_mode),
                            ('salvage_enabled', salvage_enabled),
                            ('domain_models', domain_models),
                            ('provider_client', has_provider_client),
                            ('metrics_http', metrics_http),
                            ('build_info_registered', build_info_registered),
                            ('overrides_count', overrides_count),
                            ('egress_frozen', egress_frozen),
                            ('start_timestamp', start_ts),
                        ],
                        logger
                    )
                except Exception:
                    pass
            logger.info(
                "orchestrator.summary loop_interval=%s indices=%s pipeline_v2=%s diff_mode=%s structured_sse=%s quiet=%s salvage=%s domain_models=%s provider_client=%s metrics_http=%s build_info=%s overrides=%s egress_frozen=%s start_ts=%s",
                loop_interval, indices_count, pipeline_v2, diff_mode, structured_sse, quiet_mode, salvage_enabled,
                domain_models, has_provider_client, metrics_http, build_info_registered, overrides_count, egress_frozen, start_ts
            )
            try:
                from src.observability.startup_summaries import register_or_note_summary
                register_or_note_summary('orchestrator', emitted=True)
            except Exception:
                pass
            # JSON variant
            try:
                from src.utils.env_flags import is_truthy_env as _orch_truthy
                if _orch_truthy('G6_ORCH_SUMMARY_JSON'):
                    from src.utils.summary_json import emit_summary_json
                    emit_summary_json(
                        'orchestrator',
                        [
                            ('loop_interval', loop_interval),
                            ('indices_count', indices_count),
                            ('pipeline_v2', pipeline_v2),
                            ('diff_mode', diff_mode),
                            ('structured_sse', structured_sse),
                            ('quiet_mode', quiet_mode),
                            ('salvage_enabled', salvage_enabled),
                            ('domain_models', domain_models),
                            ('provider_client', has_provider_client),
                            ('metrics_http', metrics_http),
                            ('build_info_registered', build_info_registered),
                            ('overrides_count', overrides_count),
                            ('egress_frozen', egress_frozen),
                            ('start_timestamp', start_ts),
                        ],
                        logger_override=logger
                    )
            except Exception:
                pass
    except Exception:
        pass
    # Force collector settings hydration early so its one-shot summary is emitted under captured logger
    try:
        from src.collector.settings import get_collector_settings
        # If sentinel was cleared by a previous test, re-hydration will emit structured + optional JSON/human summaries
        get_collector_settings(force_reload=True)
    except Exception:
        logger.debug("collector settings early hydration failed", exc_info=True)
    return ctx, metrics_stop

# Emit deprecated env vars presence summary (JSON optional) via dispatcher convenience
try:  # registration happens at import time (idempotent)
    from src.observability.startup_summaries import register_summary
    from src.utils.env_flags import is_truthy_env
    def _emit_deprecated_env_summary() -> bool:
        try:
            from src.config.env_lifecycle import ENV_LIFECYCLE_REGISTRY
        except Exception:
            return False
        present = []
        for entry in ENV_LIFECYCLE_REGISTRY:
            try:
                if getattr(entry, 'status', '') == 'deprecated' and entry.name in os.environ:
                    present.append(entry.name)
            except Exception:
                continue
        if not present:
            # still emit a zero-count line for visibility
            logging.getLogger(__name__).info("env.deprecations.summary count=0")
            if is_truthy_env('G6_ENV_DEPRECATIONS_SUMMARY_JSON'):
                try:
                    from src.utils.summary_json import emit_summary_json
                    emit_summary_json('env.deprecations', [('count', 0)], logger_override=logging.getLogger(__name__))
                except Exception:
                    pass
            return True
        log = logging.getLogger(__name__)
        log.info("env.deprecations.summary count=%s names=%s", len(present), ','.join(present))
        if is_truthy_env('G6_ENV_DEPRECATIONS_SUMMARY_JSON'):
            try:
                from src.utils.summary_json import emit_summary_json
                emit_summary_json('env.deprecations', [('count', len(present)), ('names', present)], logger_override=log)
            except Exception:
                pass
        return True
    from src.observability.startup_summaries import register_or_note_summary
    # Ensure callable registered for dispatcher emission + mark not yet emitted
    register_summary('env.deprecations', _emit_deprecated_env_summary)
    register_or_note_summary('env.deprecations', emitted=False)
except Exception:
    pass

__all__ = ["bootstrap_runtime", "run_env_deprecation_scan"]
