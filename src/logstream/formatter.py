"""Structured concise rolling log stream formatting.

Goal: produce single-line, information-dense records emitted each cycle / per-index
so that: (a) human tail in terminal is useful, (b) future dashboard can parse
directly without needing Prometheus scrape for basic stream view.

Log Line Types (prefix token):
  CYCLE  - one per completed overall collection cycle
  INDEX  - one per index after its expiries processed
  ERROR  - error events (optional enrichment)

Format (KEY=VAL space-delimited, no spaces in values; predictable ordering):
  CYCLE ts=1699999999 dur=1.42 opts=12345 opts_per_min=521.3 cpu=12.4 mem_mb=512.3
        api_ms=83.1 api_succ=99.2 coll_succ=97.5 indices=4 stall=0
  INDEX ts=1699999999 idx=NIFTY legs=345 succ=92.5 legs_avg=312 legs_cum=123456
        attempts=4 fail=0 age_s=0 pcr=1.02 atm=22450 err=none status=ok

Parsing: split once on first space for type token, then key=value pairs.
Durable: avoid removal of keys; add new keys at end to preserve backward compat.
"""
from __future__ import annotations

import time
from typing import Any

from src.utils.color import colorize, severity_color

ISO_TS = False  # if True, include human time; keep false for headless ingestion

def _ts() -> str:
    now = time.time()
    return str(int(now)) if not ISO_TS else time.strftime('%Y-%m-%dT%H:%M:%S', time.localtime(now))

def format_cycle(
    *,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    parts = ["CYCLE", f"ts={_ts()}"]
    parts.append(f"dur={duration_s:.2f}")
    parts.append(f"opts={options}")
    if options_per_min is not None:
        parts.append(f"opts_per_min={options_per_min:.1f}")
    if cpu is not None:
        parts.append(f"cpu={cpu:.1f}")
    if mem_mb is not None:
        parts.append(f"mem_mb={mem_mb:.1f}")
    if api_latency_ms is not None:
        parts.append(f"api_ms={api_latency_ms:.1f}")
    if api_success_pct is not None:
        parts.append(f"api_succ={api_success_pct:.1f}")
    if collection_success_pct is not None:
        parts.append(f"coll_succ={collection_success_pct:.1f}")
    parts.append(f"indices={indices}")
    if stall_flag is not None:
        parts.append(f"stall={stall_flag}")
    if extra:
        for k,v in extra.items():
            # sanitize spaces
            if isinstance(v, float):
                parts.append(f"{k}={v:.3f}")
            else:
                parts.append(f"{k}={v}")
    return ' '.join(parts)

def format_index(
    *,
    index: str,
    legs: int,
    legs_avg: float | None,
    legs_cum: int | None,
    succ_pct: float | None,
    succ_avg_pct: float | None,
    attempts: int | None,
    failures: int | None,
    last_age_s: float | None,
    pcr: float | None,
    atm: float | None,
    err: str | None,
    status: str,
    extra: dict[str, Any] | None = None,
) -> str:
    parts = ["INDEX", f"ts={_ts()}", f"idx={index}", f"legs={legs}"]
    if legs_avg is not None:
        parts.append(f"legs_avg={int(legs_avg)}")
    if legs_cum is not None:
        parts.append(f"legs_cum={legs_cum}")
    if succ_pct is not None:
        parts.append(f"succ={succ_pct:.1f}")
    if succ_avg_pct is not None:
        parts.append(f"succ_avg={succ_avg_pct:.1f}")
    if attempts is not None:
        parts.append(f"attempts={attempts}")
    if failures is not None:
        parts.append(f"fail={failures}")
    if last_age_s is not None:
        parts.append(f"age_s={int(last_age_s)}")
    if pcr is not None:
        parts.append(f"pcr={pcr:.2f}")
    if atm is not None:
        parts.append(f"atm={int(atm)}")
    parts.append(f"err={(err or 'none')}")
    parts.append(f"status={status}")
    if extra:
        for k,v in extra.items():
            if isinstance(v, float):
                parts.append(f"{k}={v:.3f}")
            else:
                parts.append(f"{k}={v}")
    return ' '.join(parts)

def format_start(*, version: str, indices: int, interval_s: int, concise: bool, extra: dict[str, Any] | None = None) -> str:
    parts = ["START", f"ts={_ts()}", f"ver={version}", f"indices={indices}", f"interval_s={interval_s}", f"concise={'1' if concise else '0'}"]
    if extra:
        for k,v in extra.items():
            if isinstance(v, float):
                parts.append(f"{k}={v:.3f}")
            else:
                parts.append(f"{k}={v}")
    return ' '.join(parts)

def format_cycle_pretty(*,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
) -> str:
    """Return a human-friendly multi-metric summary line for a cycle.

    Includes anomaly flags:
      - NO_DATA when options == 0
      - DEGRADED when success rates < 90% (api or collection)
      - STALL when stall_flag is truthy
    """
    status_tokens: list[str] = []
    if options == 0:
        status_tokens.append('NO_DATA')
    if (api_success_pct is not None and api_success_pct < 90) or (collection_success_pct is not None and collection_success_pct < 90):
        status_tokens.append('DEGRADED')
    if stall_flag:
        status_tokens.append('STALL')
    if not status_tokens:
        status_tokens.append('OK')
    status = '+'.join(status_tokens)
    # Build aligned columns
    opm = f"{options_per_min:.1f}" if options_per_min is not None else '-'
    cpu_str = f"{cpu:.1f}%" if cpu is not None else '-'
    mem_str = f"{mem_mb:.1f}MB" if mem_mb is not None else '-'
    api_ms = f"{api_latency_ms:.1f}ms" if api_latency_ms is not None else '-'
    api_s = f"{api_success_pct:.1f}%" if api_success_pct is not None else '-'
    coll_s = f"{collection_success_pct:.1f}%" if collection_success_pct is not None else '-'
    stall = str(stall_flag) if stall_flag is not None else '-'
    return (
        f"CYCLE_SUMMARY dur={duration_s:.2f}s opts={options} opm={opm} api={api_ms} api_succ={api_s} "
        f"coll_succ={coll_s} cpu={cpu_str} mem={mem_str} indices={indices} stall={stall} status={status}"
    )

def format_cycle_table(*,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
) -> tuple[str, str]:
    """Return (header_line, value_line) for cycle metrics.

    Logged separately so each line carries its own timestamp / logger prefix for readability.
    """
    status_tokens: list[str] = []
    if options == 0:
        status_tokens.append('NO_DATA')
    if (api_success_pct is not None and api_success_pct < 90) or (collection_success_pct is not None and collection_success_pct < 90):
        status_tokens.append('DEGRADED')
    if stall_flag:
        status_tokens.append('STALL')
    if not status_tokens:
        status_tokens.append('OK')
    status = '+'.join(status_tokens)

    # Prepare raw values (without units for sizing, then append units where useful)
    row = {
        'Dur(s)': f"{duration_s:.2f}",
        'Opts': str(options),
        'OpM': f"{options_per_min:.1f}" if options_per_min is not None else '-',
        'API(ms)': f"{api_latency_ms:.1f}" if api_latency_ms is not None else '-',
        'API%': f"{api_success_pct:.1f}" if api_success_pct is not None else '-',
        'Coll%': f"{collection_success_pct:.1f}" if collection_success_pct is not None else '-',
        'CPU%': f"{cpu:.1f}" if cpu is not None else '-',
        'Mem(MB)': f"{mem_mb:.1f}" if mem_mb is not None else '-',
        'Idx': str(indices),
        'Stall': str(stall_flag) if stall_flag is not None else '-',
        'Status': status,
    }
    headers = list(row.keys())
    # Compute widths
    widths = {h: max(len(h), len(row[h])) for h in headers}
    # Build header line
    header_line = ' '.join(f"{h:<{widths[h]}}" for h in headers)
    # Apply color AFTER width calc so we don't distort alignment (raw width measurement used plain text above)
    colored_values = []
    for h in headers:
        val = row[h]
        if h == 'Status':
            col, bold = severity_color(val)
            val = colorize(val, col, bold=bold)
        colored_values.append(f"{val:<{widths[h]}}")
    value_line = ' '.join(colored_values)
    return header_line, value_line

__all__ = [
    'format_cycle', 'format_index', 'format_start', 'format_cycle_pretty', 'format_cycle_table', 'format_cycle_readable'
]

def format_cycle_readable(*,
    duration_s: float,
    options: int,
    options_per_min: float | None,
    cpu: float | None,
    mem_mb: float | None,
    api_latency_ms: float | None,
    api_success_pct: float | None,
    collection_success_pct: float | None,
    indices: int,
    stall_flag: int | None = None,
) -> str:
    """Return a human-readable single line summary (no abbreviations).

    Example:
      CYCLE_READABLE duration=0.82s options=410 (per_min=1023.4) api_latency=83.1ms api_success=99.2% collection_success=98.7% cpu=12.4% mem=512.3MB indices=4 stall=- status=OK

    Keeps machine-friendly key=value pairs while improving clarity for operators.
    """
    status_tokens: list[str] = []
    if options == 0:
        status_tokens.append('NO_DATA')
    if (api_success_pct is not None and api_success_pct < 90) or (collection_success_pct is not None and collection_success_pct < 90):
        status_tokens.append('DEGRADED')
    if stall_flag:
        status_tokens.append('STALL')
    if not status_tokens:
        status_tokens.append('OK')
    status = '+'.join(status_tokens)
    parts = ["CYCLE_READABLE"]
    parts.append(f"duration={duration_s:.2f}s")
    parts.append(f"options={options}")
    if options_per_min is not None:
        parts.append(f"per_min={options_per_min:.1f}")
    if api_latency_ms is not None:
        parts.append(f"api_latency={api_latency_ms:.1f}ms")
    if api_success_pct is not None:
        parts.append(f"api_success={api_success_pct:.1f}%")
    if collection_success_pct is not None:
        parts.append(f"collection_success={collection_success_pct:.1f}%")
    if cpu is not None:
        parts.append(f"cpu={cpu:.1f}%")
    if mem_mb is not None:
        parts.append(f"mem={mem_mb:.1f}MB")
    parts.append(f"indices={indices}")
    parts.append(f"stall={stall_flag if stall_flag is not None else '-'}")
    parts.append(f"status={status}")
    return ' '.join(parts)
