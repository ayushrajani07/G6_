"""Data catalog emission utility (enriched).

Produces `data/catalog.json` summarizing the freshest option chain artifacts
per index/expiry and (optionally) a tail of recent structured events.

Enrichment Features:
    * Last CSV file path + mtime (existing minimal behavior).
    * Option count (row count minus header) and last row raw value (for quick diff).
    * Attempt extraction of a timestamp from the last row (best-effort heuristics).
    * Recent event lines (sequence aware) with optional context stripping.
    * Last observed event sequence number.

Environment Flags:
    G6_EMIT_CATALOG=1              -> enable emission (triggered by status_writer)
    G6_EMIT_CATALOG_EVENTS=1       -> include recent events section
    G6_CATALOG_EVENTS_LIMIT=20     -> max events to include (default 20)
    G6_CATALOG_EVENTS_CONTEXT=0    -> exclude context objects from catalog events

Graceful Degradation:
    * Fails quietly (logs debug) if CSV parsing or event reading errors occur.
    * Omits fields instead of raising when data unavailable.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from src.utils.env_flags import is_truthy_env  # type: ignore

logger = logging.getLogger(__name__)

CATALOG_PATH = Path("data/catalog.json")

def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).isoformat().replace('+00:00','Z')

_EPOCH_RE = re.compile(r"^\d{10}(?:\.\d+)?$")  # naive epoch seconds pattern
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:")

def _parse_last_row_meta(path: Path) -> tuple[int | None, str | None, str | None]:
    """Return (option_count, last_row_raw, derived_timestamp_iso?) for CSV file.

    We assume header is first line. We only read file once streaming to avoid memory use.
    Timestamp heuristic: first token in last row if it matches epoch or ISO pattern.
    """
    try:
        option_count = 0
        last_line: str | None = None
        with open(path, encoding='utf-8', errors='ignore') as fh:
            first = True
            for line in fh:
                line = line.rstrip('\n')
                if first:
                    first = False
                    continue  # skip header
                if line.strip():
                    option_count += 1
                    last_line = line
        if last_line is None:
            return 0, None, None
        derived_ts: str | None = None
        cells = last_line.split(',') if ',' in last_line else [last_line]
        if cells:
            candidate = cells[0].strip().strip('"')
            if _EPOCH_RE.match(candidate):
                try:
                    derived_ts = _iso(float(candidate))
                except Exception:
                    derived_ts = None
            elif _ISO_RE.match(candidate):
                derived_ts = candidate
        return option_count, last_line, derived_ts
    except Exception:  # pragma: no cover - defensive
        logger.debug("catalog: failed parsing CSV last row meta for %s", path, exc_info=True)
        return None, None, None


def _gather_recent_events() -> tuple[list[dict], int | None]:
    limit = int(os.environ.get('G6_CATALOG_EVENTS_LIMIT', '20'))
    if limit <= 0:
        return [], None
    include_ctx = os.environ.get('G6_CATALOG_EVENTS_CONTEXT','1').lower() not in ('0','false','no','off')
    events: list[dict] = []
    last_seq: int | None = None
    # Prefer in-process event API if available (gives us recent buffer without reading disk again)
    try:
        from src.events.event_log import get_recent_events  # type: ignore
        events = get_recent_events(limit=limit, include_context=include_ctx)  # newest first
        if events:
            last_seq = events[0].get('seq')
        return events, last_seq
    except Exception:
        # Fallback: read tail of file
        path = os.environ.get('G6_EVENTS_LOG_PATH', os.path.join('logs','events.log'))
        try:
            p = Path(path)
            if not p.exists():
                return [], None
            # Read file lines (bounded by limit*2 to be safe)
            lines = p.read_text(encoding='utf-8', errors='ignore').strip().splitlines()
            take = lines[-limit:]
            parsed: list[dict] = []
            for ln in reversed(take):  # newest first
                try:
                    obj = json.loads(ln)
                    if not include_ctx and 'context' in obj:
                        del obj['context']
                    parsed.append(obj)
                except Exception:
                    continue
            if parsed:
                last_seq = parsed[0].get('seq')
            return parsed, last_seq
        except Exception:  # pragma: no cover
            logger.debug("catalog: failed reading events fallback", exc_info=True)
            return [], None


def build_catalog(*, runtime_status_path: str, csv_dir: str = "data/g6_data") -> dict[str, Any]:
    indices: list[str] = []
    try:
        with open(runtime_status_path, encoding='utf-8') as fh:
            status = json.load(fh)
        indices = status.get('indices', []) or []
    except Exception:
        logger.debug("catalog: unable to read runtime status at %s", runtime_status_path)
    now_ts = dt.datetime.now(dt.UTC).timestamp()
    catalog: dict[str, Any] = {"generated_at": _iso(now_ts), "indices": {}}
    # We'll accumulate per-index rollups to emit index-level summary & global summary.
    global_latest_ts: float | None = None
    global_option_count = 0
    base = Path(csv_dir)
    for idx in indices:
        idx_dir = base / idx
        if not idx_dir.exists():
            continue
        index_option_count = 0
        index_latest_ts: float | None = None
        expiries = {}
        try:
            for expiry_dir in idx_dir.iterdir():
                if not expiry_dir.is_dir():
                    continue
                latest_file = None
                latest_mtime = 0.0
                try:
                    for f in expiry_dir.glob('*.csv'):
                        mt = f.stat().st_mtime
                        if mt > latest_mtime:
                            latest_mtime = mt
                            latest_file = f
                except Exception:
                    pass
                if latest_file:
                    opt_count, last_row_raw, derived_ts = _parse_last_row_meta(latest_file)
                    entry: dict[str, Any] = {
                        "last_file": str(latest_file),
                        "last_file_mtime": _iso(latest_mtime)
                    }
                    if opt_count is not None:
                        entry["option_count"] = opt_count
                        index_option_count += opt_count or 0
                    if last_row_raw is not None:
                        entry["last_row_raw"] = last_row_raw
                    if derived_ts is not None:
                        entry["last_row_timestamp"] = derived_ts
                        # Track latest timestamp heuristically per index / globally.
                        try:
                            # Convert derived_ts (ISO or already ISO) to epoch for comparison.
                            # Accept both already ISO and epoch-like we converted earlier.
                            parsed_dt = None
                            if derived_ts.endswith('Z') or 'T' in derived_ts:
                                parsed_dt = dt.datetime.fromisoformat(derived_ts.replace('Z','+00:00'))
                            if parsed_dt:
                                epoch_val = parsed_dt.timestamp()
                                if index_latest_ts is None or epoch_val > index_latest_ts:
                                    index_latest_ts = epoch_val
                                if global_latest_ts is None or epoch_val > global_latest_ts:
                                    global_latest_ts = epoch_val
                        except Exception:  # pragma: no cover - defensive
                            pass
                    expiries[expiry_dir.name] = entry
        except Exception:  # pragma: no cover - defensive directory scan failure
            logger.debug("catalog: failure scanning %s", idx_dir, exc_info=True)
        if expiries:
            idx_entry: dict[str, Any] = {"expiries": expiries}
            # Attach per-index rollup if available
            if index_option_count:
                idx_entry["total_option_count"] = index_option_count
                global_option_count += index_option_count
            if index_latest_ts is not None:
                idx_entry["latest_row_timestamp"] = _iso(index_latest_ts)
                # Derive gap in seconds relative to now (rough freshness indicator)
                gap = max(0, int(now_ts - index_latest_ts))
                idx_entry["data_gap_seconds"] = gap
            catalog["indices"][idx] = idx_entry
    # Add global summary if we surfaced any indices
    if catalog["indices"]:
        summary: dict[str, Any] = {"index_count": len(catalog["indices"]) }
        if global_option_count:
            summary["total_option_count"] = global_option_count
        if global_latest_ts is not None:
            summary["latest_row_timestamp"] = _iso(global_latest_ts)
            summary["global_data_gap_seconds"] = max(0, int(now_ts - global_latest_ts))
        catalog["summary"] = summary
    # Integrity summary (cycle gaps) enrichment (always attempted; lightweight)
    try:
        events_path = os.environ.get('G6_EVENTS_LOG_PATH', os.path.join('logs','events.log'))
        cycles: list[int] = []
        try:
            with open(events_path,encoding='utf-8') as fh:
                for i, line in enumerate(fh):
                    if i >= 200_000: break
                    line=line.strip()
                    if not line or line.startswith('#'): continue
                    if 'cycle_start' not in line:  # fast substring pre-filter
                        continue
                    try:
                        obj=json.loads(line)
                    except Exception:
                        continue
                    if obj.get('event')=='cycle_start':
                        ctx=obj.get('context') or {}
                        c=ctx.get('cycle')
                        if isinstance(c,int): cycles.append(c)
        except FileNotFoundError:
            cycles=[]
        # detect gaps inline
        missing=0
        if cycles:
            cs=sorted(set(cycles))
            for a,b in zip(cs, cs[1:], strict=False):
                if b>a+1:
                    missing += (b-a-1)
        catalog['integrity']={
            'cycles_observed': len(cycles),
            'first_cycle': min(cycles) if cycles else None,
            'last_cycle': max(cycles) if cycles else None,
            'missing_count': missing,
            'status': 'OK' if missing==0 else 'GAPS'
        }
    except Exception:  # pragma: no cover
        logger.debug("catalog: integrity computation failed", exc_info=True)
    # Optional event enrichment
    if is_truthy_env('G6_EMIT_CATALOG_EVENTS'):
        events, last_seq = _gather_recent_events()
        catalog['events_included'] = True
        catalog['recent_events'] = events
        if last_seq is not None:
            catalog['last_event_seq'] = last_seq
    else:
        catalog['events_included'] = False
    return catalog

def emit_catalog(*, runtime_status_path: str, csv_dir: str = "data/g6_data") -> None:
    cat = build_catalog(runtime_status_path=runtime_status_path, csv_dir=csv_dir)
    try:
        CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CATALOG_PATH.with_suffix('.json.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            json.dump(cat, fh, indent=2, sort_keys=True)
        os.replace(tmp, CATALOG_PATH)
    except Exception:  # pragma: no cover
        logger.warning("catalog: failed to write catalog.json", exc_info=True)

__all__ = ["build_catalog", "emit_catalog", "CATALOG_PATH"]
