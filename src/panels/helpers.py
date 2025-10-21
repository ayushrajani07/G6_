"""Common helpers for panels computations (status, reasons, thresholds).

This module centralizes small bits of logic used across the panels factory,
web dashboard metrics cache, and optional publisher paths to avoid drift.
"""
from __future__ import annotations

from typing import Literal

Style = Literal['panels', 'web']


def compute_status_and_reason(
    *,
    success_pct: float | None,
    legs: int | None,
    err_recent: bool = False,
    err_type: str | None = None,
    style: Style = 'panels',
    # Thresholds (defaults mirror existing behavior in callers)
    ok_threshold: int = 95,
    warn_floor: int = 80,  # panels: >= warn_floor and < ok -> WARN; < warn_floor -> ERROR
    web_warn_threshold: int = 92,  # web: succ < 92 -> warn
) -> tuple[str, str | None]:
    """Return a (status, reason) tuple for given inputs.

    - style='panels': returns status in {'OK','WARN','ERROR'}
      policy: if success is None -> OK; elif >= ok_threshold -> OK; elif >= warn_floor -> WARN; else ERROR
      reasons: 'no legs this cycle' if legs==0; 'no success metric' if success None and status not OK;
               'low success XX%' if < warn_floor; 'success XX%' if WARN with borderline success.

    - style='web': returns status in {'ok','warn','bad'}
      policy: if success is None or success < warn_floor or legs==0 -> 'bad';
              elif success < web_warn_threshold or err_recent -> 'warn'; else 'ok'.
      reasons: 'no legs this cycle', 'no success metric', 'low success XX%', 'success XX%',
               'error: <type>' if err_recent and err_type provided; 'possible stall' hint if err_type == 'stall'.
    """
    # Normalize inputs
    succ_int: int | None = None
    if isinstance(success_pct, (int, float)):
        try:
            succ_int = int(round(success_pct))
        except Exception:
            succ_int = None

    legs_int: int | None = None
    if isinstance(legs, (int, float)):
        try:
            legs_int = int(legs)
        except Exception:
            legs_int = None

    # Panels-style computation
    if style == 'panels':
        if succ_int is None or succ_int >= ok_threshold:
            status = 'OK'
        elif succ_int >= warn_floor:
            status = 'WARN'
        else:
            status = 'ERROR'
        reason: str | None = None
        if legs_int == 0:
            reason = 'no legs this cycle'
        elif succ_int is None and status in ('WARN', 'ERROR'):
            reason = 'no success metric'
        elif isinstance(succ_int, int):
            if succ_int < warn_floor:
                reason = f'low success {succ_int}%'
            elif succ_int < ok_threshold and status == 'WARN':
                reason = f'success {succ_int}%'
        return status, reason

    # Web-style computation
    status_web = 'ok'
    reason_web: str | None = None
    if succ_int is None or (isinstance(succ_int, int) and succ_int < warn_floor) or legs_int == 0:
        status_web = 'bad'
        if legs_int == 0:
            reason_web = 'no legs this cycle'
        elif succ_int is None:
            reason_web = 'no success metric'
        elif isinstance(succ_int, int):
            reason_web = f'low success {succ_int:.0f}%'
    elif (isinstance(succ_int, int) and succ_int < web_warn_threshold) or err_recent:
        status_web = 'warn'
        if err_recent and err_type:
            reason_web = f'error: {err_type}'
        elif isinstance(succ_int, int):
            reason_web = f'success {succ_int:.0f}%'
    if not reason_web and err_type == 'stall':
        reason_web = 'possible stall'
    return status_web, reason_web
