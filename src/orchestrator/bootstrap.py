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

from typing import Tuple, Any
import logging
import os

from src.orchestrator.context import RuntimeContext
from src.config.runtime_config import get_runtime_config
from src.utils.build_info import auto_register_build_info

logger = logging.getLogger(__name__)

# Deliberate shallow imports to avoid circular dependencies
try:  # pragma: no cover - optional path if metrics not yet refactored
    from src.metrics import setup_metrics_server  # facade import
except Exception:  # pragma: no cover
    setup_metrics_server = None  # type: ignore

# Use canonical config loader (ConfigWrapper) to avoid depending on legacy unified_main.
try:
    from src.config.loader import load_config  # type: ignore
except Exception:  # pragma: no cover
    try:  # fallback to legacy if new path unavailable
        from src.unified_main import load_config  # type: ignore
    except Exception:
        load_config = None  # type: ignore


def run_env_deprecation_scan(*, strict_mode_override: bool | None = None) -> None:
    """Scan environment for deprecated variables and emit warnings / raise if strict.

    Parameters
    ----------
    strict_mode_override : bool | None
        Force strict mode on/off (bypasses env flag) when not None.
    """
    try:
        from src.config.env_lifecycle import ENV_LIFECYCLE_REGISTRY  # type: ignore
        if strict_mode_override is None:
            strict_mode = os.getenv('G6_ENV_DEPRECATION_STRICT','').lower() in ('1','true','yes','on')
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
                      enable_resource_sampler: bool = True) -> Tuple[RuntimeContext, Any | None]:
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
    if load_config is None:
        raise RuntimeError("load_config unavailable; import order issue")
    raw_cfg = load_config(config_path)

    metrics = None
    metrics_stop = lambda: None
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
            from src.orchestrator.components import init_providers, init_storage, init_health, apply_circuit_breakers  # type: ignore
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
                from src.utils.market_hours import is_premarket_window, get_next_market_open  # type: ignore
                if is_premarket_window():
                    nxt = get_next_market_open()
                    logger.warning(
                        "Premarket bootstrap partial (credentials missing?). Will retry provider init automatically after regular open at %s if orchestrator restarts, or set credentials earlier to enable warm caches.",
                        nxt
                    )
            except Exception:  # pragma: no cover
                pass
    # Start catalog HTTP server if enabled
    if os.environ.get('G6_CATALOG_HTTP','').lower() in ('1','true','yes','on'):
        try:
            from src.orchestrator.catalog_http import start_http_server_in_thread  # type: ignore
            start_http_server_in_thread()
        except Exception:
            logger.exception("Catalog HTTP server failed to start")
    return ctx, metrics_stop

__all__ = ["bootstrap_runtime", "run_env_deprecation_scan"]
