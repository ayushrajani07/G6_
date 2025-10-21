#!/usr/bin/env python
"""One-shot diagnostic script to inspect raw Kite instrument universe and expiry alignment.

Usage:
  python scripts/debug_instruments.py [INDEX ...]
Defaults to core indices if none provided.

Outputs:
  - Universe size
  - Option-like counts (raw, normalized CE/PE)
  - Distinct expiries (truncated)
  - Per-index: resolved expiries vs presence in universe
  - Sample instruments
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from collections import Counter as TCounter

# Allow running even if project root not on path
if __name__ == '__main__':
    sys.path.append(os.path.abspath('.'))

from src.broker.kite_provider import KiteProvider  # type: ignore
from src.collectors.modules.expiry_helpers import resolve_expiry  # type: ignore

DEFAULT_INDICES = ["NIFTY","BANKNIFTY","FINNIFTY","SENSEX"]
indices = sys.argv[1:] or DEFAULT_INDICES

provider = KiteProvider.from_env()
provider._ensure_client()

universe = provider.get_instruments("NFO", force_refresh=True)
print(f"UNIVERSE_COUNT={len(universe)}")

opt_like = []
for inst in universe:
    seg = str(inst.get('segment','')).upper()
    ts = str(inst.get('tradingsymbol','')).upper()
    if 'OPT' in seg or 'OPT' in ts:
        opt_like.append(inst)
print(f"OPT_LIKE_COUNT={len(opt_like)}")

ity_counter: TCounter[str] = Counter()
expiries = set()
for inst in opt_like:
    ity = (inst.get('instrument_type') or '').upper()
    ts = str(inst.get('tradingsymbol','')).upper()
    if ity not in ('CE','PE'):
        if ts.endswith('CE'): ity = 'CE'
        elif ts.endswith('PE'): ity = 'PE'
    ity_counter[ity] += 1
    expv = inst.get('expiry')
    if expv:
        if hasattr(expv,'strftime'):
            expiries.add(expv.strftime('%Y-%m-%d'))
        else:
            expiries.add(str(expv)[:10])
print(f"TYPE_COUNTS={dict(ity_counter)}")
print(f"DISTINCT_EXPIRIES_TOTAL={len(expiries)}")
print("DISTINCT_EXPIRIES_SAMPLE=", sorted(list(expiries))[:20])

# Per-index expiry resolution alignment
from typing import Any

class _DummyProviders:  # minimal facade for resolve_expiry
    def __init__(self, primary: Any) -> None:
        self.primary_provider = primary
    def get_expiry_dates(self, index_symbol: str) -> Any:  # not used directly here
        return self.primary_provider.get_expiry_dates(index_symbol)

# Reuse provider as facade
providers_facade = _DummyProviders(provider)

print("\nPER_INDEX_EXPIRY_ALIGNMENT:")
for idx in indices:
    try:
        resolved = {}
        for rule in ("this_week","next_week","this_month","next_month"):
            try:
                r = resolve_expiry(idx, rule, providers_facade, metrics=None, concise_mode=True)
                resolved[rule] = r.strftime('%Y-%m-%d')
            except Exception as e:
                resolved[rule] = f"ERR:{e}"  # show error reason
        missing = {rule: date for rule,date in resolved.items() if isinstance(date,str) and date.startswith('20') and date not in expiries}
        print(f"INDEX={idx} resolved={resolved} missing_in_universe={missing}")
    except Exception as ie:
        print(f"INDEX={idx} ERROR {ie}")

# Sample instruments (first 5 option-like)
print("\nSAMPLE_INSTRUMENTS:")
for inst in opt_like[:5]:
    slim = {k: inst.get(k) for k in ('tradingsymbol','instrument_type','segment','expiry','strike','name')}
    print(json.dumps(slim, default=str))

print("\nDONE")
