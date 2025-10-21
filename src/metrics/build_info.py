#!/usr/bin/env python3
"""Build info metric registration helper (extracted from metrics.py).

Provides idempotent registration of a labeled build info gauge:
  g6_build_info{version=...,git_commit=...,config_hash=...} 1

Behavior:
- Creates gauge if absent; reuses existing collector if already registered.
- Clears previous labeled samples to avoid duplicate exposition lines on updates.
- Swallows errors defensively (mirrors original resilience semantics).
"""
from __future__ import annotations

import logging
import os
from typing import Any

from prometheus_client import REGISTRY, Gauge  # type: ignore

logger = logging.getLogger(__name__)

__all__ = ["register_build_info"]


def _get_existing(name: str):  # best-effort internal helper
    try:
        names_map = getattr(REGISTRY, "_names_to_collectors", {})  # type: ignore[attr-defined]
        return names_map.get(name)
    except Exception:  # pragma: no cover
        return None


def register_build_info(metrics: Any, version: str | None = None, git_commit: str | None = None, config_hash: str | None = None) -> None:
    """Register or update the build info gauge.

    Parameters
    ----------
    metrics : object
        Registry-like object for attribute assignment (legacy API expects attribute binding for discoverability).
    version, git_commit, config_hash : Optional str
        Override values; if not supplied falls back to environment variables
        G6_BUILD_VERSION / G6_BUILD_COMMIT / G6_BUILD_CONFIG_HASH (with 'unknown' default).
    """
    gauge = None
    try:
        # If attribute already present and resembles a Gauge reuse it
        gauge = getattr(metrics, 'build_info', None)
        if gauge is None:
            # Attempt to locate existing collector (duplicate-safe) else create
            existing = _get_existing('g6_build_info')
            if existing is not None:
                gauge = existing
            else:
                try:
                    gauge = Gauge('g6_build_info', 'Build information', ['version','git_commit','config_hash'])
                    metrics.build_info = gauge  # type: ignore[attr-defined]
                except ValueError:
                    gauge = _get_existing('g6_build_info')
        if gauge is not None:
            v = version or os.environ.get('G6_BUILD_VERSION','unknown')
            gc = git_commit or os.environ.get('G6_BUILD_COMMIT','unknown')
            ch = config_hash or os.environ.get('G6_BUILD_CONFIG_HASH','unknown')
            relabeled = False
            try:
                # Clear previous labeled samples so we maintain a single line exposition
                try:
                    metrics_dict = getattr(gauge, '_metrics', None)
                    if isinstance(metrics_dict, dict):
                        if metrics_dict:
                            relabeled = True
                        metrics_dict.clear()
                except Exception:
                    pass
                gauge.labels(version=v, git_commit=gc, config_hash=ch).set(1)  # type: ignore[attr-defined]
            except Exception:
                pass
            # Structured log for machine parsing (best-effort)
            try:
                logger.info(
                    "metrics.build_info.registered",
                    extra={
                        "event": "metrics.build_info.registered",
                        "version": v,
                        "git_commit": gc,
                        "config_hash": ch,
                        "relabeled": relabeled,
                    },
                )
            except Exception:
                pass
    except Exception:
        # Silent resilience; downstream observation remains best-effort
        pass
