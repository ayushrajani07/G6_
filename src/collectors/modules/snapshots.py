"""Snapshot construction helpers for collector pipeline.

Separated from legacy unified_collectors to reduce inline complexity.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

try:  # domain models may not be present in some reduced test contexts
    from src.domain.models import ExpirySnapshot, OptionQuote  # pragma: no cover
except Exception:  # pragma: no cover
    OptionQuote = None  # sentinel when models unavailable
    ExpirySnapshot = None  # sentinel when models unavailable


def build_expiry_snapshot(
    index: str,
    expiry_rule: str,
    expiry_date: Any,
    atm_strike: float | int | None,
    enriched_data: dict[str, dict[str, Any]],
    generated_at: Any,
) -> Any | None:
    """Build an ExpirySnapshot object from enriched option data.

    Returns the snapshot instance or None if construction failed or models unavailable.
    Behavior mirrors legacy inline logic; silently skips individual option conversion failures.
    """
    if ExpirySnapshot is None or OptionQuote is None:
        logger.debug('Snapshot models unavailable; skipping snapshot build index=%s rule=%s', index, expiry_rule)
        return None
    try:
        option_objs: list[Any] = []
        for sym, q in enriched_data.items():
            if OptionQuote is None:
                break  # no model available; skip building individual option quotes
            try:
                from_raw = getattr(OptionQuote, 'from_raw', None)
                if from_raw is None:
                    continue
                option_objs.append(from_raw(sym, q))
            except Exception:
                continue
        atm_val: float = float(atm_strike) if atm_strike is not None else 0.0
        return ExpirySnapshot(
            index=index,
            expiry_rule=expiry_rule,
            expiry_date=expiry_date,
            atm_strike=atm_val,
            options=option_objs,
            generated_at=generated_at,
        )
    except Exception:
        logger.debug('build_expiry_snapshot_failed index=%s rule=%s', index, expiry_rule, exc_info=True)
        return None
