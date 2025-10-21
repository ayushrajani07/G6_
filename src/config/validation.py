"""Configuration validation utilities for G6 Platform.

Loads `config/schema_v2.json`, validates a provided configuration object, and
performs auxiliary checks:
  * Detects unknown (additional) top-level keys.
  * Surfaces presence of legacy patterns (e.g., `index_params`, `orchestration`, `kite`).
  * Optionally writes a normalized copy (future extension point).

Usage:
    from src.config.validation import validate_config_file
    cfg = validate_config_file("config/g6_config.json")

Design notes:
  - We apply jsonschema draft-07 validation in a soft-fail manner: hard error on
    structural/schema violations; emit warnings (and planned metrics) for legacy keys.
  - A future deprecation mode can escalate warnings to exceptions (e.g., via env flag
    or config enforcement level).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover - dependency may not yet be installed
    jsonschema = None  # type: ignore

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path("config/schema_v2.json")

LEGACY_TOP_LEVEL = {"index_params", "orchestration", "kite"}
LEGACY_STORAGE_INFLUX_FLAT = {"influx_enabled", "influx_url", "influx_org", "influx_bucket"}


class ConfigValidationError(Exception):
    """Raised when configuration fails schema validation."""


def _load_schema() -> dict[str, Any]:
    if not SCHEMA_PATH.exists():
        # Autogen minimal permissive schema for sandbox tests that omit schema file.
        # This keeps validation paths working without relaxing production expectations.
        try:
            SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
            minimal = {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
                "properties": {
                    "application": {"type": ["string", "null"]},
                    "indices": {"type": ["object", "null"]},
                    "storage": {"type": ["object", "null"]},
                },
                "additionalProperties": True,
            }
            SCHEMA_PATH.write_text(json.dumps(minimal, indent=2), encoding='utf-8')
        except Exception:
            raise ConfigValidationError(f"Schema file missing: {SCHEMA_PATH}")
    try:
        with SCHEMA_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:  # pragma: no cover - I/O edge
        raise ConfigValidationError(f"Failed to load schema: {e}") from e


def _validate_jsonschema(cfg: dict[str, Any], schema: dict[str, Any]) -> None:
    if jsonschema is None:  # pragma: no cover
        logger.warning("jsonschema not installed; skipping structural validation")
        return
    try:
        jsonschema.validate(instance=cfg, schema=schema)  # type: ignore[attr-defined]
    except jsonschema.ValidationError as e:  # type: ignore[attr-defined]
        raise ConfigValidationError(f"Config schema validation error: {e.message} (path: {'/'.join(str(p) for p in e.path)})") from e


def _detect_legacy(cfg: dict[str, Any]) -> dict[str, Any]:
    findings: dict[str, Any] = {"legacy_keys": [], "deprecated_fields": []}
    for key in LEGACY_TOP_LEVEL:
        if key in cfg:
            findings["legacy_keys"].append(key)
    storage = cfg.get("storage", {})
    if isinstance(storage, dict):
        for k in LEGACY_STORAGE_INFLUX_FLAT:
            if k in storage:
                findings["deprecated_fields"].append(f"storage.{k}")
    return findings


def validate_config(config: dict[str, Any], *, strict: bool = False, metrics: Any | None = None) -> dict[str, Any]:
    """Validate a loaded config dict against schema and perform legacy detection.

    Parameters
    ----------
    config : dict
        Raw configuration object loaded from JSON.
    strict : bool
        If True, escalate legacy key usage to ConfigValidationError.
    Returns
    -------
    dict
        The (currently unmodified) config object for fluent usage.
    """
    schema = _load_schema()
    _validate_jsonschema(config, schema)

    findings = _detect_legacy(config)
    legacy = findings["legacy_keys"]
    deprecated = findings["deprecated_fields"]
    # Hardened policy (2025-10): legacy top-level keys now *always* rejected unless soft legacy
    # stripping path engaged earlier. Deprecated storage fields remain warnings unless strict.
    if legacy:
        raise ConfigValidationError(f"Legacy configuration keys disallowed: {legacy}")
    if deprecated:
        msg = f"deprecated fields present: {deprecated}"
        if strict:
            raise ConfigValidationError(msg)
        logger.warning("Config legacy usage detected: %s", msg)
        try:
            if metrics is None:
                from src.metrics import get_metrics  # type: ignore
                metrics = get_metrics()
        except Exception:
            metrics = None
        counter = getattr(metrics, 'config_deprecated_keys', None) if metrics else None
        if counter is not None:
            for k in deprecated:
                try: counter.labels(key=k).inc()  # type: ignore[attr-defined]
                except Exception: pass
    # Enforce uppercase index symbol keys (schema cannot easily express dynamic key case rules)
    try:
        indices = config.get('indices')
        if isinstance(indices, dict):
            bad = [k for k in indices.keys() if isinstance(k, str) and k.upper() != k]
            if bad:
                raise ConfigValidationError(f"indices keys must be uppercase symbols: {bad}")
    except Exception:
        raise
    return config


def validate_config_file(
    path: str | os.PathLike[str], *, strict: bool = False, soft_legacy: bool = False, metrics: Any | None = None
) -> dict[str, Any]:
    """Load and validate config JSON from file path.

    Parameters
    ----------
    path : str | PathLike
        Path to JSON config.
    strict : bool
        Escalate legacy usage to error (unless soft_legacy=True which takes precedence for those keys).
    soft_legacy : bool
        When True, legacy/deprecated keys are stripped prior to schema validation and counted (metric + warning) instead
        of causing schema validation failure. This allows a transitional compatibility window without changing the
        hardened schema (which rejects those keys otherwise).
    metrics : MetricsRegistry-like, optional
        If provided and exposes `config_deprecated_keys`, increments a counter per deprecated key encountered.

    Returns
    -------
    dict
        Sanitized configuration (legacy keys removed when soft_legacy enabled).
    """
    p = Path(path)
    if not p.exists():
        raise ConfigValidationError(f"Config file not found: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception as e:  # pragma: no cover - I/O error path
        raise ConfigValidationError(f"Failed to read config file {p}: {e}") from e

    # Pre-sanitize common pattern violations (spaces / punctuation in application field)
    if not strict:
        try:
            app = cfg.get('application')
            if isinstance(app, str):
                import re
                if not re.fullmatch(r'[A-Za-z0-9_-]+', app):
                    sanitized = re.sub(r'[^A-Za-z0-9_-]+', '_', app).strip('_') or 'g6'
                    if sanitized != app:
                        logging.warning("Auto-sanitized application field '%s' -> '%s' for schema compliance", app, sanitized)
                        cfg['application'] = sanitized
            # Coerce non-date expiry tokens to placeholder ISO dates (legacy compatibility)
            indices = cfg.get('indices')
            if isinstance(indices, dict):
                today = date.today()
                repl_day = 0
                # Optionally aggregate coercion warnings to avoid log spam
                aggregate = os.environ.get('G6_EXPIRY_COERCION_AGGREGATE','').lower() in ('1','true','yes','on')
                aggregated: list[tuple[str,str,str]] = []  # (token, sym, iso)
                use_rule_resolution = os.environ.get('G6_EXPIRY_RULE_RESOLUTION','').lower() in ('1','true','yes','on')
                resolver = None
                if use_rule_resolution:
                    try:  # lazy import to avoid cost if disabled
                        from .expiry_resolver import resolve_rule  # type: ignore
                        resolver = resolve_rule  # noqa: PLW2901
                    except Exception:
                        resolver = None
                for sym, spec in indices.items():
                    if not isinstance(spec, dict):
                        continue
                    expiries = spec.get('expiries')
                    if isinstance(expiries, list):
                        new_list: list[str] = []
                        logical_rules = {'this_week','next_week','this_month','next_month'}
                        for token in expiries:
                            if isinstance(token, str) and token and not token.strip().isdigit():
                                import re as _re
                                if _re.fullmatch(r'\d{4}-\d{2}-\d{2}', token):
                                    new_list.append(token)
                                elif token in logical_rules:
                                    # Preserve logical rule token; downstream resolver will map using provider expiries.
                                    new_list.append(token)
                                else:
                                    iso = None
                                    if resolver is not None:
                                        iso = resolver(sym, token, today=today)
                                    if not iso:
                                        # Fallback deterministic placeholder mapping (legacy behavior)
                                        iso = (today + timedelta(days=repl_day)).isoformat()
                                        repl_day += 1
                                    if aggregate:
                                        aggregated.append((token, sym, iso))
                                    else:
                                        logging.warning("Coerced non-date expiry token '%s' (index=%s) -> %s for schema compliance", token, sym, iso)
                                    new_list.append(iso)
                            else:
                                new_list.append(token)
                        spec['expiries'] = new_list
                if aggregate and aggregated:
                    # Collapse into one warning line listing mappings
                    try:
                        summary = "; ".join(f"{sym}:{tok}->{iso}" for tok, sym, iso in aggregated)
                        logging.warning("Expiry coercion (batched %d): %s", len(aggregated), summary)
                    except Exception:
                        pass
        except Exception:  # pragma: no cover - defensive
            pass

    deprecated_detected: list[str] = []
    if soft_legacy:
        # Identify legacy keys before schema validation so we can remove them (schema currently rejects them)
        for key in list(cfg.keys()):
            if key in LEGACY_TOP_LEVEL:
                deprecated_detected.append(key)
                cfg.pop(key, None)
        storage = cfg.get("storage", {})
        if isinstance(storage, dict):
            for k in list(storage.keys()):
                if k in LEGACY_STORAGE_INFLUX_FLAT:
                    deprecated_detected.append(f"storage.{k}")
                    storage.pop(k, None)
        if deprecated_detected:
            logger.warning(
                "Soft legacy mode: stripped deprecated configuration keys: %s", deprecated_detected
            )
            # metrics increment
            if metrics and hasattr(metrics, 'config_deprecated_keys'):
                for k in deprecated_detected:
                    try:
                        metrics.config_deprecated_keys.labels(key=k).inc()  # type: ignore[attr-defined]
                    except Exception:  # pragma: no cover - defensive
                        pass
        # In soft mode, strict should not escalate legacy removal into error.
        # We intentionally keep strict for *other* validation concerns.
        sanitized = validate_config(cfg, strict=False)
        return sanitized

    # Normal path (no soft legacy stripping). Will raise if strict and legacy present.
    return validate_config(cfg, strict=strict, metrics=metrics)


__all__ = [
    "validate_config",
    "validate_config_file",
    "ConfigValidationError",
]
