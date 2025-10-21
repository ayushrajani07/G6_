#!/usr/bin/env python3
"""
Schema version definitions and helpers for the G6 configuration system.

Non-invasive and optional: existing code can continue to use ConfigWrapper.
"""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any


class SchemaVersion(Enum):
    UNVERSIONED = 0
    V1_0 = 1
    V1_1 = 2
    V1_2 = 3
    V1_3 = 4

    @classmethod
    def latest(cls) -> SchemaVersion:
        return cls.V1_3

    @classmethod
    def from_string(cls, version_str: str) -> SchemaVersion:
        v = (version_str or "").strip().lower()
        mapping = {
            "1.0": cls.V1_0,
            "1.1": cls.V1_1,
            "1.2": cls.V1_2,
            "1.3": cls.V1_3,
        }
        return mapping.get(v, cls.UNVERSIONED)


# Migration registry: target version -> function
MigrationFunc = Callable[[dict[str, Any]], dict[str, Any]]
MIGRATIONS: dict[SchemaVersion, MigrationFunc] = {}


def register_migration(target_version: SchemaVersion):
    def deco(func: MigrationFunc) -> MigrationFunc:
        MIGRATIONS[target_version] = func
        return func
    return deco


def get_config_version(cfg: dict[str, Any]) -> SchemaVersion:
    if not isinstance(cfg, dict):
        return SchemaVersion.UNVERSIONED
    ver = cfg.get("schema_version")
    if isinstance(ver, str):
        return SchemaVersion.from_string(ver)
    # Heuristics for unversioned
    if isinstance(cfg.get("health"), dict) and isinstance(cfg.get("storage", {}).get("influx"), dict):  # type: ignore[index]
        return SchemaVersion.V1_3
    if isinstance(cfg.get("storage", {}).get("influx"), dict):  # type: ignore[index]
        return SchemaVersion.V1_2
    if isinstance(cfg.get("greeks"), dict):
        return SchemaVersion.V1_1
    return SchemaVersion.V1_0


def get_required_migrations(cfg: dict[str, Any], target: SchemaVersion | None = None) -> list[SchemaVersion]:
    tgt = target or SchemaVersion.latest()
    cur = get_config_version(cfg)
    if cur.value >= tgt.value:
        return []
    return [v for v in SchemaVersion if v.value > cur.value and v.value <= tgt.value]


__all__ = [
    "SchemaVersion",
    "MigrationFunc",
    "MIGRATIONS",
    "register_migration",
    "get_config_version",
    "get_required_migrations",
]
