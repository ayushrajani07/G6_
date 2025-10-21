#!/usr/bin/env python3
"""Introspection & init trace dump helpers (extracted from metrics.py).

Provides resilient, environment-driven JSON dump routines for:
  - Metrics introspection inventory (G6_METRICS_INTROSPECTION_DUMP)
  - Initialization step trace (G6_METRICS_INIT_TRACE_DUMP)

Accepted values for each env var:
  stdout  -> pretty JSON logged at INFO
  temp    -> writes to a temp file (named g6_metrics_*_trace_*.json)
  <path>  -> writes JSON to the specified path
  any truthy ("1", "true", etc.) -> treated as stdout

All operations are best-effort and swallow exceptions (mirroring historical behavior).
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time as _t
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "maybe_dump_introspection",
    "maybe_dump_init_trace",
    "run_post_init_dumps",
]


def _normalize_flag(val: str) -> str:
    v = val.strip()
    if not v:
        return ""
    if v.lower() in {"1", "true", "yes", "on"}:
        return "stdout"
    return v


def maybe_dump_introspection(registry: Any) -> None:
    flag_raw = os.getenv("G6_METRICS_INTROSPECTION_DUMP", "").strip()
    flag = _normalize_flag(flag_raw)
    if not flag:
        return
    try:
        inv = getattr(registry, "_metrics_introspection", None)
        if inv is None:
            # Lazy build if not yet constructed
            try:
                from .introspection import build_introspection_inventory as _bii  # type: ignore
                registry._metrics_introspection = _bii(registry)  # type: ignore[attr-defined]
                inv = registry._metrics_introspection
            except Exception:
                inv = []
                registry._metrics_introspection = []  # type: ignore[attr-defined]
        payload = {
            "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "metric_count": len(inv),
            "groups_present": sorted({g for g in (m.get("group") for m in inv) if g}),
            "inventory": inv,
        }
        if flag.lower() == "stdout":
            logger.info(
                "METRICS_INTROSPECTION:\n" + json.dumps(payload, indent=2, sort_keys=True)
            )
        else:
            out_path = flag
            if flag.lower() == "temp":
                out_path = os.path.join(tempfile.gettempdir(), "g6_metrics_introspection.json")
            with open(out_path, "w", encoding="utf-8") as fh:  # pragma: no cover
                json.dump(payload, fh, indent=2, sort_keys=True)
            logger.info(
                "Metrics introspection written to %s (%d metrics)",
                out_path,
                len(inv),
            )
        # Structured log for machine parsing
        try:
            logger.info(
                "metrics.introspection.dump",
                extra={
                    "event": "metrics.introspection.dump",
                    "metric_count": len(inv),
                    "groups_present": payload.get("groups_present", []),
                    "output": flag,
                },
            )
        except Exception:  # pragma: no cover
            pass
    except Exception as e:  # pragma: no cover
        try:
            logger.warning("Failed to dump metrics introspection (%s): %s", flag, e)
        except Exception:
            pass


def maybe_dump_init_trace(registry: Any) -> None:
    flag_raw = os.getenv("G6_METRICS_INIT_TRACE_DUMP", "").strip()
    flag = _normalize_flag(flag_raw)
    if not flag:
        return
    try:
        trace = getattr(registry, "_init_trace", [])
        if not trace:
            return
        tdump = {
            "steps": trace,
            "total_steps": len(trace),
            "total_time": sum(r.get("dt", 0.0) for r in trace),
        }
        if flag.lower() == "stdout":
            logger.info(
                "METRICS_INIT_TRACE:\n" + json.dumps(tdump, indent=2, sort_keys=True)
            )
        else:
            out_path = flag
            if flag.lower() == "temp":
                out_path = os.path.join(
                    tempfile.gettempdir(), f"g6_metrics_init_trace_{int(_t.time())}.json"
                )
            with open(out_path, "w", encoding="utf-8") as fh:  # pragma: no cover
                json.dump(tdump, fh, indent=2, sort_keys=True)
            logger.info(
                "Metrics init trace written to %s (%d steps)", out_path, len(trace)
            )
        # Structured log for machine parsing
        try:
            logger.info(
                "metrics.init_trace.dump",
                extra={
                    "event": "metrics.init_trace.dump",
                    "total_steps": len(trace),
                    "total_time": tdump.get("total_time"),
                    "output": flag,
                },
            )
        except Exception:  # pragma: no cover
            pass
    except Exception as e:  # pragma: no cover
        try:
            logger.warning("Failed to dump metrics init trace (%s): %s", flag, e)
        except Exception:
            pass


def run_post_init_dumps(registry: Any) -> None:
    """Invoke both introspection and init trace dumps best-effort."""
    maybe_dump_introspection(registry)
    maybe_dump_init_trace(registry)
