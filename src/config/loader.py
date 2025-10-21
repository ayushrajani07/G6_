from __future__ import annotations

"""Config loading & normalization entrypoint.

Responsibilities:
  * Load raw JSON file.
  * Validate against schema (strict or soft) via validation module.
  * Detect legacy/deprecated keys; increment metrics counter if available.
  * Emit normalized config to logs/normalized_config.json (optional toggle).

Environment Flags:
  G6_CONFIG_STRICT=1            -> escalate legacy usage to error.
  G6_CONFIG_EMIT_NORMALIZED=1   -> write normalized config JSON file.

Public API:
  load_and_validate_config(path: str, metrics=None) -> dict
"""
import json
import logging
import os
from pathlib import Path
from typing import Any

from .config_wrapper import ConfigWrapper  # canonical wrapper for normalized access
from .validation import ConfigValidationError, validate_config_file


class ConfigError(ConfigValidationError):  # backward compatibility alias
    pass

logger = logging.getLogger(__name__)

NORMALIZED_PATH = Path("logs/normalized_config.json")

def _emit_normalized(cfg: dict[str, Any]) -> None:
    try:
        NORMALIZED_PATH.parent.mkdir(parents=True, exist_ok=True)
        with NORMALIZED_PATH.open('w', encoding='utf-8') as fh:
            json.dump(cfg, fh, indent=2, sort_keys=True)
    except Exception:  # pragma: no cover - best effort
        logger.warning("Failed to write normalized config", exc_info=True)


def _increment_deprecated_metrics(cfg: dict[str, Any], metrics: Any) -> None:
    if not metrics or not hasattr(metrics, 'config_deprecated_keys'):
        return
    # Re-run lightweight legacy detection inline (avoid importing validation internals)
    legacy_keys = []
    for k in ("index_params", "orchestration", "kite"):
        if k in cfg:
            legacy_keys.append(k)
    storage = cfg.get("storage", {})
    if isinstance(storage, dict):
        for k in ("influx_enabled", "influx_url", "influx_org", "influx_bucket"):
            if k in storage:
                legacy_keys.append(f"storage.{k}")
    for key in legacy_keys:
        try:
            metrics.config_deprecated_keys.labels(key=key).inc()
        except Exception:
            pass


def load_and_validate_config(path: str | os.PathLike[str], *, metrics: Any = None) -> dict[str, Any]:
    strict = os.environ.get('G6_CONFIG_STRICT','').lower() in ('1','true','yes','on')
    soft_legacy = os.environ.get('G6_CONFIG_LEGACY_SOFT','').lower() in ('1','true','yes','on')
    try:
        cfg = validate_config_file(path, strict=strict, soft_legacy=soft_legacy, metrics=metrics)
    except ConfigValidationError as e:
        # Graceful downgrade for common, low-risk pattern violations (e.g., application name with spaces)
        msg = str(e)
        if not strict and 'application' in msg and 'does not match' in msg:
            try:
                # Reload raw JSON directly and attempt sanitization
                with open(path, encoding='utf-8') as fh:
                    raw = json.load(fh)
                app = raw.get('application')
                if isinstance(app, str):
                    import re
                    sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', app).strip('_') or 'g6'
                    if sanitized != app:
                        raw['application'] = sanitized
                        logger.warning("Auto-sanitized application field '%s' -> '%s' to satisfy schema pattern", app, sanitized)
                        # Validate again (will raise if still invalid for other reasons)
                        # Use validate_config_file logic on a temp in-memory path? Reuse validate_config on raw.
                        from .validation import validate_config
                        validate_config(raw, strict=False)
                        cfg = raw
                    else:
                        raise
                else:
                    raise
            except Exception:
                raise
        else:
            # Attempt expiry token coercion fallback (rule tokens -> deterministic ISO dates)
            if not strict and 'expiries' in msg and 'does not match' in msg:
                try:
                    with open(path, encoding='utf-8') as fh:
                        raw2 = json.load(fh)
                    from datetime import date, timedelta
                    today = date.today()
                    changed = False
                    indices = raw2.get('indices')
                    if isinstance(indices, dict):
                        delta = 0
                        for sym, spec in indices.items():
                            if not isinstance(spec, dict):
                                continue
                            exps = spec.get('expiries')
                            if isinstance(exps, list):
                                new_exps = []
                                import re as _re
                                for token in exps:
                                    if isinstance(token, str) and not _re.fullmatch(r'\d{4}-\d{2}-\d{2}', token):
                                        iso = (today + timedelta(days=delta)).isoformat()
                                        delta += 1
                                        new_exps.append(iso)
                                        changed = True
                                    else:
                                        new_exps.append(token)
                                spec['expiries'] = new_exps
                    if changed:
                        # Revalidate transformed config (legacy detection off strict)
                        from .validation import validate_config
                        validate_config(raw2, strict=False)
                        cfg = raw2
                    else:
                        raise
                except Exception:
                    raise
            else:
                raise
    # Optional normalized emit
    if os.environ.get('G6_CONFIG_EMIT_NORMALIZED','').lower() in ('1','true','yes','on'):
        _emit_normalized(cfg)
    _increment_deprecated_metrics(cfg, metrics)
    # Optional provider capability validation: ensure configured provider names map to objects
    # exposing required callables. This is a lightweight runtime safeguard to catch miswired
    # provider implementations early (e.g., missing get_index_data for composite provider).
    if os.environ.get('G6_CONFIG_VALIDATE_CAPABILITIES','').lower() in ('1','true','yes','on'):
        required = ['get_index_data', 'get_option_chain']
        # Providers referenced implicitly via config indices section; attempt dynamic import of src.providers if present
        problems: list[str] = []
        try:
            from src import providers as _prov_mod
        except Exception:  # pragma: no cover - if providers module absent we skip
            _prov_mod = None
        # Heuristic: if providers module exposes a registry dict, use it; else introspect attributes
        registry = {}
        try:
            if _prov_mod is not None:
                cand = getattr(_prov_mod, 'REGISTRY', None)
                if isinstance(cand, dict):
                    registry = cand
                else:  # collect callables/classes starting with capital letter
                    for _name in dir(_prov_mod):
                        if _name.startswith('_'):
                            continue
                        obj = getattr(_prov_mod, _name)
                        registry[_name] = obj
        except Exception:
            pass
        indices = cfg.get('indices') or {}
        if isinstance(indices, dict):
            for idx, params in indices.items():
                if not isinstance(params, dict):
                    continue
                provider_name = params.get('provider') or params.get('provider_name')
                if not provider_name:
                    continue  # may rely on default provider wiring
                provider_obj = registry.get(provider_name)
                if provider_obj is None:
                    problems.append(f"E-PROV-NOTFOUND:{idx}:{provider_name}")
                    continue
                for r in required:
                    if not hasattr(provider_obj, r):
                        problems.append(f"E-PROV-MISSING:{idx}:{provider_name}:{r}")
        if problems:
            # Raise aggregated error for clarity. Use ConfigValidationError to align with existing handling.
            detail = ';'.join(problems)
            raise ConfigValidationError(f"Provider capability validation failed: {detail}")
    return cfg

def load_and_process_config(config_path: str, *_, **__) -> tuple[dict, list[str]]:
    """Backward compatible wrapper used by legacy bootstrap.

    Ignores legacy migration/env override flags; returns (config, warnings_list).
    """
    cfg = load_and_validate_config(config_path)
    return cfg, []


def load_config(path: str, *, metrics: Any | None = None) -> ConfigWrapper:
    """Canonical high-level loader returning ConfigWrapper.

    This consolidates legacy `unified_main.load_config` and the raw dict loaders
    into a single entrypoint so new orchestrator/bootstrap code no longer needs
    to import from `unified_main`.

    Environment flags (strict, normalized emit, capability validation) are
    honored via `load_and_validate_config`.
    """
    raw = load_and_validate_config(path, metrics=metrics)
    return ConfigWrapper(raw)

__all__ = [
    "load_and_validate_config",
    "load_config",
    "ConfigValidationError",
    "load_and_process_config",
    "ConfigError",
]
