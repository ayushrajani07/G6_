#!/usr/bin/env python3
"""
Config migration engine. Applies optional, non-breaking migrations to bring
configs to the latest schema. By default, not used unless enabled via loader
or environment flag (see loader.py).
"""
from __future__ import annotations

import copy
import logging
from typing import Any

from .schema_versions import (
    MIGRATIONS,
    SchemaVersion,
    get_required_migrations,
    register_migration,
)

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    pass


def migrate_config(cfg: dict[str, Any], target: SchemaVersion | None = None) -> dict[str, Any]:
    tgt = target or SchemaVersion.latest()
    work = copy.deepcopy(cfg)
    order = get_required_migrations(work, tgt)
    for v in order:
        fn = MIGRATIONS.get(v)
        if not fn:
            logger.debug("No migrator registered for %s; skipping", v)
            continue
        try:
            work = fn(work)
        except Exception as e:  # pragma: no cover
            raise MigrationError(f"Failed migrating to {v}: {e}")
    # Stamp version for clarity
    work["schema_version"] = {
        SchemaVersion.V1_0: "1.0",
        SchemaVersion.V1_1: "1.1",
        SchemaVersion.V1_2: "1.2",
        SchemaVersion.V1_3: "1.3",
    }[tgt]
    return work


@register_migration(SchemaVersion.V1_0)
def _to_v1_0(cfg: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    out.setdefault("providers", {"primary": {}})
    out.setdefault("index_params", {})
    return out


@register_migration(SchemaVersion.V1_1)
def _to_v1_1(cfg: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    out.setdefault("greeks", {
        "enabled": False,
        "estimate_iv": False,
        "risk_free_rate": 0.055,
        "iv_max_iterations": 100,
        "iv_min": 0.01,
        "iv_max": 2.0,
        "iv_precision": 1e-5,
    })
    return out


@register_migration(SchemaVersion.V1_2)
def _to_v1_2(cfg: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    storage = out.setdefault("storage", {})
    # Move top-level influx to storage.influx
    if isinstance(out.get("influx"), dict) and not isinstance(storage.get("influx"), dict):
        storage["influx"] = out.pop("influx")
    # Move flat fields
    mapping = {
        "influx_enabled": ("influx", "enabled"),
        "influx_url": ("influx", "url"),
        "influx_token": ("influx", "token"),
        "influx_org": ("influx", "org"),
        "influx_bucket": ("influx", "bucket"),
    }
    for flat_key, (sect, key) in mapping.items():
        if flat_key in storage:
            storage.setdefault(sect, {})[key] = storage.pop(flat_key)
    # CSV subsection (non-breaking; mirror csv_dir if present)
    if "csv" not in storage:
        csv_dir = storage.get("csv_dir", "data/g6_data")
        storage["csv"] = {
            "dir": csv_dir,
            "buffer_size": storage.get("csv_buffer_size", 0),
            "max_open_files": storage.get("csv_max_open_files", 64),
            "flush_interval_seconds": storage.get("csv_flush_interval_seconds", 2.0),
        }
    return out


@register_migration(SchemaVersion.V1_3)
def _to_v1_3(cfg: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    health = out.setdefault("health", {})
    health.setdefault("api", {"enabled": False, "host": "127.0.0.1", "port": 8099})
    health.setdefault("prometheus", {"enabled": False})
    health.setdefault("alerts", {"enabled": False, "state_directory": "data/health/alerts", "channels": [], "policies": []})
    return out


__all__ = ["migrate_config", "MigrationError"]
