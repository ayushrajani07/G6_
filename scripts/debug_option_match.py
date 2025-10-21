#!/usr/bin/env python
"""
Direct option match probe.

Steps:
 1. Initialize KiteProvider (auto .env load already present).
 2. For target indices (default: NIFTY,BANKNIFTY), resolve expiries: this_week,next_week.
 3. Build strike list around ATM (ATM +/- {0,100,200,300}).
 4. Call option_instruments via provider delegate for each (index, expiry_rule).
 5. Print diagnostics: expiry resolved date, strikes requested, filtered universe size snapshot, match count, relaxed fallback logs expected.

Environment flags respected:
  G6_RELAX_EMPTY_MATCH (default on) for relaxed fallback.
  G6_CONCISE_LOGS=0 to make sure detailed logs show.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

os.environ.setdefault('G6_RELAX_EMPTY_MATCH','1')
os.environ.setdefault('G6_CONCISE_LOGS','0')

try:
    from src.broker.kite.options import option_instruments
    from src.broker.kite_provider import KiteProvider
    from src.collectors.modules.expiry_helpers import resolve_expiry
except Exception as e:  # pragma: no cover
    print("IMPORT_FAIL", e)
    raise SystemExit(1)

INDICES = os.environ.get('G6_DEBUG_OPTION_INDICES','NIFTY,BANKNIFTY').split(',')
RULES = ['this_week','next_week']

prov = KiteProvider()

report: list[dict[str, Any]] = []
for idx in [i.strip().upper() for i in INDICES if i.strip()] :
    for rule in RULES:
        try:
            exp_date = resolve_expiry(idx, rule, prov, metrics=None, concise_mode=True)
        except Exception as e:
            report.append({'index': idx, 'rule': rule, 'error': f'resolve:{type(e).__name__}:{e}'})
            continue
        atm = prov.get_atm_strike(idx)
        # Build strikes (guard atm int)
        base = int(atm) if isinstance(atm,(int,float)) and not math.isnan(float(atm)) else 0
        increments = [0, 100, 200, 300]
        strikes: list[float] = []
        for inc in increments:
            strikes.append(float(base + inc))
            if inc != 0:
                strikes.append(float(base - inc))
        strikes = sorted(set(s for s in strikes if s > 0))
        try:
            insts = option_instruments(prov, idx, exp_date, strikes)
        except Exception as e:
            report.append({'index': idx, 'rule': rule, 'expiry': str(exp_date), 'strikes': len(strikes), 'error': f'option_instruments:{type(e).__name__}:{e}'})
            continue
        report.append({
            'index': idx,
            'rule': rule,
            'expiry': str(exp_date),
            'atm': base,
            'strikes_requested': len(strikes),
            'match_count': len(insts),
            'sample': [i.get('tradingsymbol') for i in insts[:4]],
        })

print(json.dumps(report, indent=2))
