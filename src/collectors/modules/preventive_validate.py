"""Phase 6: Preventive Validation Extraction

Wraps the legacy `preventive_validation_stage` helper adding optional debug
snapshot emission (G6_PREVENTIVE_DEBUG) while keeping behavior identical.

Public API:
    run_preventive_validation(index_symbol, rule, expiry_date, instruments, enriched, index_price) -> (cleaned_enriched, report)

Snapshot Behavior (debug mode only):
- Writes two JSON snapshots (instruments head + enriched head) under:
    data/debug_preventive/<index>/<rule>/
- Filenames: <ts>_01_instruments.json , <ts>_02_enriched_head.json (parity with legacy)

Notes:
- We purposefully truncate to first 500 items like legacy for safety.
- Failures in snapshotting never raise; they only log debug.
"""
from __future__ import annotations
from typing import Any, Dict, List, Tuple
import os, datetime, json, pathlib, logging

logger = logging.getLogger(__name__)

try:  # pragma: no cover
    from src.collectors.helpers.validation import preventive_validation_stage as _preventive_validation_stage  # type: ignore
except Exception:  # pragma: no cover
    def _preventive_validation_stage(index_symbol, rule, expiry_date, instruments, enriched, index_price):  # type: ignore
        return enriched, { 'skipped': True }

__all__ = ["run_preventive_validation"]


def run_preventive_validation(index_symbol: str, rule: str, expiry_date, instruments: List[Dict[str, Any]], enriched: Dict[str, Any], index_price: float | None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    preventive_debug = os.environ.get('G6_PREVENTIVE_DEBUG','0').lower() in ('1','true','yes','on')
    snap_root = None
    ts_key = None
    if preventive_debug:
        try:
            snap_root = pathlib.Path('data') / 'debug_preventive' / index_symbol / rule
            snap_root.mkdir(parents=True, exist_ok=True)
            ts_key = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')
            with open(snap_root / f'{ts_key}_01_instruments.json','w', encoding='utf-8') as f:
                json.dump({'index': index_symbol,'expiry_rule': rule,'expiry_date': str(expiry_date),'count': len(instruments),'records': instruments[:500]}, f, indent=2)
            head = list(enriched.items())[:500]
            with open(snap_root / f'{ts_key}_02_enriched_head.json','w', encoding='utf-8') as f:
                json.dump({'index': index_symbol,'expiry_rule': rule,'sample_count': len(head),'records': [{k:v} for k,v in head]}, f, indent=2)
        except Exception:
            logger.debug('preventive_snapshot_failed', exc_info=True)
    try:
        cleaned_data, report = _preventive_validation_stage(index_symbol, rule, expiry_date, instruments, enriched, index_price)
    except Exception:
        logger.debug('preventive_validation_failed', exc_info=True)
        cleaned_data, report = enriched, { 'error': True }
    return cleaned_data, report
