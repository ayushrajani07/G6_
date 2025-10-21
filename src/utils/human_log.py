#!/usr/bin/env python3
"""Human-friendly multi-line log formatting helpers.

Purpose: Provide an optional, low-noise aligned block for critical one-shot
startup summaries (settings, environment, capability gates) to complement
single-line structured logs.

Design Goals:
- Zero heavy imports (safe very-early import)
- Graceful fallback if any field coercion fails
- Width-adaptive alignment based on longest key
- Optional ANSI dim styling (disabled by default to keep logs copy/paste safe)
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = ["emit_human_summary"]

def _coerce_pairs(fields: Mapping[str, Any] | Iterable[tuple[str, Any]]):
    if isinstance(fields, dict):
        return list(fields.items())
    try:
        return list(fields)  # type: ignore[arg-type]
    except Exception:
        return []

def emit_human_summary(title: str, fields: Mapping[str, Any] | Iterable[tuple[str, Any]], logger: logging.Logger | None = None, *, level: int = logging.INFO, prefix: str = "  ") -> None:
    """Emit a human-readable aligned block.

    Example:
        SETTINGS SUMMARY
          min_volume              : 0
          salvage_enabled         : 0
          outage_threshold        : 3

    Args:
        title: Heading line (uppercased automatically)
        fields: Mapping or sequence of (key,value)
        logger: Optional logger (default: module logger)
        level: Logging level
        prefix: Left padding for field lines
    """
    log = logger or logging.getLogger(__name__)
    pairs = _coerce_pairs(fields)
    if not pairs:
        return
    try:
        width = min(48, max(len(str(k)) for k,_ in pairs))
    except Exception:
        width = 32
    lines = [title.upper()]
    for k,v in pairs:
        try:
            sk = str(k)
        except Exception:
            continue
        try:
            sv = str(v)
        except Exception:
            sv = "<err>"
        lines.append(f"{prefix}{sk.ljust(width)} : {sv}")
    block = "\n".join(lines)
    try:
        log.log(level, "\n%s", block)
    except Exception:
        pass
