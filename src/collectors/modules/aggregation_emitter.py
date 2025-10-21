"""Backward compatibility shim.

`aggregation_emitter` has been superseded by `aggregation_overview`.
This module re-exports `emit_overview_aggregation` for existing imports.
Will be removed after downstream code fully migrates.
"""
from __future__ import annotations

from src.collectors.modules.aggregation_overview import emit_overview_aggregation  # noqa: F401

__all__ = ["emit_overview_aggregation"]
