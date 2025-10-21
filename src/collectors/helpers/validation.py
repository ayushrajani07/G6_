"""Preventive validation stage helper extracted from unified_collectors.

Encapsulates optional import of the preventive validator and standardized
fallback semantics so the main collector loop stays slimmer.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

__all__ = ["preventive_validation_stage"]


def preventive_validation_stage(
    index_symbol: str,
    expiry_rule: str,
    expiry_date,
    instruments,
    enriched_data,
    index_price: float,
):
    """Run preventive validator prior to downstream processing (unless bypassed).

    Bypass:
        Set env G6_VALIDATION_BYPASS=1 (or true/yes/on) to skip all preventive validation
        logic and forward enriched_data unchanged. This is a surgical switch intended for
        troubleshooting scenarios where aggressive filtering (e.g. foreign_expiry) prevents
        downstream persistence. When bypassed, a synthetic report with ok=True and
        issues=['bypassed'] is returned.

    Returns (cleaned_enriched_data, report_dict).
    Falls back gracefully if validator is missing or raises.
    """
    if os.environ.get("G6_VALIDATION_BYPASS", "0").lower() in ("1", "true", "yes", "on"):
        # Minimal synthetic report; do not mutate enriched_data
        return enriched_data, {"ok": True, "issues": ["bypassed"], "bypass": True}

    try:
        from src.validation.preventive_validator import validate_option_batch  # type: ignore
    except Exception:
        return enriched_data, {"ok": True, "issues": ["validator_import_failed"]}

    try:
        report = validate_option_batch(
            index_symbol,
            expiry_rule,
            expiry_date,
            instruments,
            enriched_data,
            index_price or 0.0,
            config=None,
        )
    except Exception as e:  # pragma: no cover (defensive)
        logger.debug("preventive validator raised: %s", e, exc_info=True)
        return enriched_data, {"ok": False, "issues": ["validator_exception"], "error": str(e)}

    cleaned = report.get("cleaned_data", enriched_data)
    return cleaned, report
