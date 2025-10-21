"""Formatting helpers for collector concise-mode output."""
from __future__ import annotations

import datetime
from collections.abc import Iterable
from typing import Any

__all__ = ["format_concise_expiry_row"]

def format_concise_expiry_row(
    *,
    per_index_ts: datetime.datetime,
    index_price: float | int | None,
    atm_strike: float | int | None,
    expiry_date: Any,
    expiry_rule: str,
    enriched_data: dict[str, dict[str, Any]],
    strikes: Iterable[float] | None,
) -> tuple[str,str,str,str,str,str,str,str,str,str,str]:
    """Produce the human row tuple used in concise mode.

    Mirrors legacy inline logic exactly (ordering & formatting) to preserve parity.
    Returns tuple of 11 strings.
    """
    # Time (UTC HH:MM)
    try:
        ts_local = per_index_ts.astimezone(datetime.UTC).strftime('%H:%M')
    except Exception:
        ts_local = '--:--'
    # Price formatting
    if isinstance(index_price,(int,float)):
        price_disp = f"{float(index_price):.2f}"
    else:
        price_disp = '-'
    # ATM formatting
    if isinstance(atm_strike,(int,float)):
        try:
            atm_disp = f"{int(atm_strike)}"
        except Exception:
            atm_disp = '-'
    else:
        atm_disp = '-'
    # Counts & OI aggregation
    legs = len(enriched_data)
    ce_count = 0; pe_count = 0; call_oi = 0.0; put_oi = 0.0
    for _q in enriched_data.values():
        try:
            _t = (_q.get('instrument_type') or _q.get('type') or '').upper()
        except Exception:
            continue
        if _t == 'CE':
            ce_count += 1
            try: call_oi += float(_q.get('oi',0) or 0)
            except Exception: pass
        elif _t == 'PE':
            pe_count += 1
            try: put_oi += float(_q.get('oi',0) or 0)
            except Exception: pass
    if call_oi > 0:
        pcr_val = (put_oi / call_oi)
    else:
        pcr_val = (pe_count / ce_count) if ce_count > 0 else 0.0
    # Strike range & step
    rng_disp = '-'; step_val_h = 0
    strike_list: list[float] = []
    if strikes:
        try:
            strike_list = list(strikes)
        except Exception:
            strike_list = []
    if strike_list:
        try:
            rng_min = int(min(strike_list)); rng_max = int(max(strike_list))
            diffs_f = [int(b-a) for a,b in zip(strike_list, strike_list[1:], strict=False) if b > a]
            step_val_h = min(diffs_f) if diffs_f else 0
            rng_disp = f"{rng_min}\u2013{rng_max}"
        except Exception:
            rng_disp='-'; step_val_h=0
    tag_map={'this_week':'This week','next_week':'Next week','this_month':'This month','next_month':'Next month'}
    tag = tag_map.get(expiry_rule, expiry_rule) or '-'
    return (
        ts_local,
        price_disp,
        atm_disp,
        str(expiry_date),
        str(tag),
        str(legs),
        str(ce_count),
        str(pe_count),
        f"{pcr_val:.2f}",
        rng_disp,
        str(step_val_h),
    )
