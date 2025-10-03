"""Snapshot construction helpers for collector pipeline.

Separated from legacy unified_collectors to reduce inline complexity.
"""
from __future__ import annotations
from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)

try:  # domain models may not be present in some reduced test contexts
    from src.domain.models import OptionQuote, ExpirySnapshot  # type: ignore
except Exception:  # pragma: no cover
    OptionQuote = None  # type: ignore
    ExpirySnapshot = None  # type: ignore


def build_expiry_snapshot(
    index: str,
    expiry_rule: str,
    expiry_date,
    atm_strike: float | int | None,
    enriched_data: Dict[str, Dict[str, Any]],
    generated_at,
) -> Any | None:
    """Build an ExpirySnapshot object from enriched option data.

    Returns the snapshot instance or None if construction failed or models unavailable.
    Behavior mirrors legacy inline logic; silently skips individual option conversion failures.
    """
    if ExpirySnapshot is None or OptionQuote is None:
        logger.debug('Snapshot models unavailable; skipping snapshot build index=%s rule=%s', index, expiry_rule)
        return None
    try:
        option_objs: List[Any] = []
        for sym, q in enriched_data.items():
            try:
                option_objs.append(OptionQuote.from_raw(sym, q))  # type: ignore[attr-defined]
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
