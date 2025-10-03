"""Phase 3: Coverage evaluation extraction.

Re-export existing coverage metric helpers to create a stable boundary. We keep
function names identical for seamless substitution later.
"""
from __future__ import annotations
from typing import Any, Dict

from src.collectors.helpers.coverage import coverage_metrics as _legacy_coverage_metrics, field_coverage_metrics as _legacy_field_coverage_metrics

__all__ = ["coverage_metrics", "field_coverage_metrics"]

def coverage_metrics(ctx, instruments, strikes, index_symbol, expiry_rule, expiry_date):  # passthrough
    return _legacy_coverage_metrics(ctx, instruments, strikes, index_symbol, expiry_rule, expiry_date)

def field_coverage_metrics(ctx, enriched_data, index_symbol, expiry_rule, expiry_date):  # passthrough
    return _legacy_field_coverage_metrics(ctx, enriched_data, index_symbol, expiry_rule, expiry_date)
