"""Central validation package.

Provides pluggable, ordered validators for option chain rows and per-expiry
aggregates. Validators are pure functions returning (data, report) where
report is a dict capturing any corrections or flags.

Design Principles:
- No side effects (logging only on debug path).
- Never fabricate synthetic data (post-synthetic-removal invariant).
- Fail closed: a validator may drop clearly invalid rows rather than inventing
  placeholders.
- Composable: validators register themselves via register_validator or using
a decorator for explicit order.

Public API:
  register_validator(fn, *, name=None, order=100)
  run_validators(context, rows) -> (clean_rows, reports)

Context object may include index symbol, expiry rule/date, env flags, metrics.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

ValidatorFn = Callable[[dict[str, Any], dict[str, Any]], tuple[dict[str, Any] | None, dict[str, Any] | None]]
# signature: (row, ctx) -> (maybe_row, per_row_report)

_VALIDATORS: list[tuple[int, str, ValidatorFn]] = []  # (order, name, fn)


def register_validator(fn: ValidatorFn | None = None, *, name: str | None = None, order: int = 100):
    """Register a validator.

    Usage patterns supported:
      @register_validator(order=10)
      def my_validator(row, ctx): ...

      @register_validator
      def my_validator(row, ctx): ...

      register_validator(my_validator, order=10)
    """

    def _decorate(f: ValidatorFn):
        ident = name or f.__name__
        _VALIDATORS.append((order, ident, f))
        # keep list ordered for deterministic execution
        _VALIDATORS.sort(key=lambda t: t[0])
        # lightweight debug (can be toggled by log level)
        logger.debug('validator_registered', extra={'validator': ident, 'order': order})
        return f

    # Decorator (no immediate function provided)
    if fn is None:
        return _decorate
    # Direct call style
    return _decorate(fn)


def list_validators() -> list[str]:
    return [n for _, n, _ in _VALIDATORS]


def _debug_dump():  # internal helper
    return [(o, n) for o, n, _ in _VALIDATORS]


def run_validators(context: dict[str, Any], rows: list[dict[str, Any]]):
    """Run all registered validators sequentially.

    Each validator can:
      - Return (row, report) to keep row (optionally mutated) and attach report.
      - Return (None, report) to drop the row.
      - Raise: will be caught and logged (row kept unchanged, error noted in reports list).
    """
    cleaned: list[dict[str, Any]] = []
    reports: list[dict[str, Any]] = []
    for row in rows:
        keep = True
        current = row
        per_row_reports: list[dict[str, Any]] = []
        for order, name, fn in _VALIDATORS:
            try:
                new_row, rep = fn(current, context)
                if rep:
                    r = dict(rep)
                    r.setdefault('validator', name)
                    reports.append(r)
                    per_row_reports.append(r)
                if new_row is None:
                    keep = False
                    break
                current = new_row
            except Exception as e:  # pragma: no cover - defensive
                logger.debug('validator_failed', extra={'validator': name, 'error': str(e)}, exc_info=True)
                reports.append({'validator': name, 'error': str(e), 'exception': True})
        if keep:
            cleaned.append(current)
    return cleaned, reports

# ---------------------------------------------------------------------------
# Built-in validators
# ---------------------------------------------------------------------------
def drop_zero_price(row: dict[str, Any], ctx: dict[str, Any]):
    lp = row.get('last_price')
    if lp in (None, 0, 0.0):
        return None, {'reason': 'zero_last_price'}
    return row, None

def clamp_negative_oi_volume(row: dict[str, Any], ctx: dict[str, Any]):
    changed = False
    for fld in ('oi', 'volume'):
        v = row.get(fld)
        if isinstance(v, (int, float)) and v < 0:
            row[fld] = 0
            changed = True
    if changed:
        return row, {'reason': 'clamp_neg_oi_vol'}
    return row, None

def basic_field_presence(row: dict[str, Any], ctx: dict[str, Any]):
    required = ('last_price','oi','volume','strike','instrument_type')
    missing = [f for f in required if f not in row]
    if missing:
        return None, {'reason': 'missing_fields', 'fields': missing}
    return row, None

def dummy_pattern_filter(row: dict[str, Any], ctx: dict[str, Any]):
    """Filter out classic uniform synthetic-looking CE/PE duplicates (post-synthetic removal safety net)."""
    # Heuristic: identical CE/PE prices around small cluster with tiny volumes
    price = row.get('last_price')
    vol = row.get('volume')
    oi = row.get('oi')
    # Updated heuristic: require strictly positive tiny oi/vol to classify as dummy.
    # Rows that have both oi and volume clamped to zero are retained (treated as sparse but not dummy duplicates).
    if (
        isinstance(price, (int, float)) and 0 < price < 1500 and
        isinstance(vol, (int, float)) and vol in (1, 2, 3, 4, 5) and  # exclude 0 volume to avoid over-filtering
        isinstance(oi, (int, float)) and 0 < oi < 10
    ):
        return None, {'reason': 'dummy_pattern'}
    return row, None

# Explicit registration (order preserved)
register_validator(drop_zero_price, order=10)
register_validator(clamp_negative_oi_volume, order=20)
register_validator(basic_field_presence, order=30)
register_validator(dummy_pattern_filter, order=40)
