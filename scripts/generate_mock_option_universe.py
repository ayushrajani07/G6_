#!/usr/bin/env python3
"""
Generate a deterministic mock option universe for preventive validation testing.

# G6_PREVENTIVE_DEBUG

Creates instrument + quote JSON snapshots for each (index, expiry_tag, offset) combination.
Optionally injects corruption patterns to test upstream validators.

Outputs directory (default): data/mock_universe/<index>/<expiry_tag>/
  - instruments.json
  - quotes.json
  - merged.json (joined view)

Corruption flags:
  --inject-mixed-expiry : Random subset of instruments gets a different expiry_date
  --inject-bad-strikes  : Introduce non-numeric / negative strike values
  --inject-dummy-expiry : Add a bogus future expiry (e.g., 2099-12-31) row

Usage examples:
  python scripts/generate_mock_option_universe.py --indices NIFTY,BANKNIFTY --expiry-tags this_week,next_week --offset-range -500 500 100
  python scripts/generate_mock_option_universe.py --inject-mixed-expiry --inject-bad-strikes --inject-dummy-expiry
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import random
from typing import Any, cast

VALID_INDICES = ["NIFTY","BANKNIFTY","FINNIFTY","SENSEX","MIDCPNIFTY"]
DEFAULT_EXPIRY_TAGS = ["this_week","next_week","this_month","next_month"]

RANDOM_SEED = 42  # deterministic
random.seed(RANDOM_SEED)

ATM_BASE = {
    "NIFTY": 24800,
    "BANKNIFTY": 54200,
    "FINNIFTY": 25900,
    "SENSEX": 80900,
    "MIDCPNIFTY": 22000,
}

WEEKLY_STEP = {
    "NIFTY": 50,
    "FINNIFTY": 50,
    "MIDCPNIFTY": 25,
    "BANKNIFTY": 100,
    "SENSEX": 100,
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Generate mock option universe")
    ap.add_argument("--indices", default=",".join(VALID_INDICES), help="Comma separated indices")
    ap.add_argument("--expiry-tags", default=",".join(DEFAULT_EXPIRY_TAGS), help="Comma separated expiry tags")
    ap.add_argument("--offset-range", nargs=3, metavar=("MIN","MAX","STEP"), default=["-300","300","50"], help="Offset sweep bounds")
    ap.add_argument("--output-base", default="data/mock_universe", help="Output root directory")
    # Corruption toggles
    ap.add_argument("--inject-mixed-expiry", action="store_true")
    ap.add_argument("--inject-bad-strikes", action="store_true")
    ap.add_argument("--inject-dummy-expiry", action="store_true")
    return ap.parse_args()


def compute_expiry(base: datetime.date, tag: str) -> datetime.date:
    # Simplified deterministic mapping (approximation for testing)
    if tag in ("this_week", "next_week"):
        # Assume weekly expiry Thursday (offset to next Thursday) plus a week for next_week
        days_ahead = (3 - base.weekday()) % 7  # Thursday == 3
        expiry_this = base + datetime.timedelta(days=days_ahead)
        if tag == "this_week":
            return expiry_this
        return expiry_this + datetime.timedelta(days=7)
    # Monthly: last Thursday concept simplified -> last weekday of month
    first_next = (base.replace(day=1) + datetime.timedelta(days=32)).replace(day=1)
    last_day = first_next - datetime.timedelta(days=1)
    # Move backwards to a weekday (Mon-Fri)
    while last_day.weekday() >= 5:
        last_day -= datetime.timedelta(days=1)
    if tag == "this_month":
        return last_day
    # next_month
    first_after = (first_next + datetime.timedelta(days=32)).replace(day=1)
    last_next = first_after - datetime.timedelta(days=1)
    while last_next.weekday() >= 5:
        last_next -= datetime.timedelta(days=1)
    return last_next


def generate_index_tag(index: str, tag: str, offsets: list[int], today: datetime.date, args: argparse.Namespace) -> dict[str, Any]:
    atm = ATM_BASE.get(index, 10000)
    step = WEEKLY_STEP.get(index, 50)
    expiry_date = compute_expiry(today, tag)
    instruments: list[dict[str, Any]] = []
    quotes: dict[str, dict[str, Any]] = {}
    for off in offsets:
        strike = atm + off
        ce_symbol = f"{index}{expiry_date.strftime('%y%m%d')}{int(strike)}CE"
        pe_symbol = f"{index}{expiry_date.strftime('%y%m%d')}{int(strike)}PE"
        for symbol, itype in [(ce_symbol,'CE'),(pe_symbol,'PE')]:
            inst = {
                'tradingsymbol': symbol,
                'strike': strike,
                'expiry': expiry_date.strftime('%Y-%m-%d'),
                'instrument_type': itype
            }
            instruments.append(inst)
            price = max(0.5, round(random.uniform(5, 250) * (1 + abs(off)/max(step,1) * 0.02), 2))
            quotes[symbol] = {
                'last_price': price,
                'oi': random.randint(100, 5000),
                'volume': random.randint(10, 10000),
                'avg_price': round(price * random.uniform(0.95, 1.05), 2),
                'instrument_type': itype,
                'strike': strike,
                'expiry': expiry_date.strftime('%Y-%m-%d')
            }
    # Corruption injections
    if args.inject_mixed_expiry and instruments:
        corrupt_expiry = (expiry_date + datetime.timedelta(days=14)).strftime('%Y-%m-%d')
        for inst in instruments[::7]:
            inst['expiry'] = corrupt_expiry
        for sym in list(quotes.keys())[::11]:
            q = quotes.get(sym)
            if q is not None:
                q['expiry'] = corrupt_expiry
    if args.inject_bad_strikes and instruments:
        instruments[0]['strike'] = 'BAD'
        instruments[-1]['strike'] = -123
    if args.inject_dummy_expiry and instruments:
        dummy = '2099-12-31'
        inst = {
            'tradingsymbol': f"{index}{dummy.replace('-','')}DUMMYCE",
            'strike': atm,
            'expiry': dummy,
            'instrument_type': 'CE'
        }
        instruments.append(inst)
        ts_val = inst.get('tradingsymbol')
        ts = ts_val if isinstance(ts_val, str) else f"{index}{dummy.replace('-','')}DUMMYCE"
        quotes[ts] = {
            'last_price': 1.0,
            'oi': 0,
            'volume': 0,
            'avg_price': 1.0,
            'instrument_type': 'CE',
            'strike': atm,
            'expiry': dummy
        }
    return {
        'expiry_date': expiry_date.strftime('%Y-%m-%d'),
        'instruments': instruments,
        'quotes': quotes
    }


def main() -> None:
    args = parse_args()
    today = datetime.date.today()
    indices = [i.strip() for i in args.indices.split(',') if i.strip()]
    tags = [t.strip() for t in args.expiry_tags.split(',') if t.strip()]
    off_min, off_max, off_step = map(int, args.offset_range)
    offsets = list(range(off_min, off_max+1, off_step))

    for index in indices:
        for tag in tags:
            data = generate_index_tag(index, tag, offsets, today, args)
            out_dir = os.path.join(args.output_base, index, tag)
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, 'instruments.json'),'w') as f:
                json.dump({'index': index, 'expiry_tag': tag, **data}, f, indent=2)
            with open(os.path.join(out_dir, 'quotes.json'),'w') as f:
                json.dump({'index': index, 'expiry_tag': tag, 'quotes': data['quotes']}, f, indent=2)
            # merged view
            merged: list[dict[str, Any]] = []
            inst_list = cast(list[dict[str, Any]], data['instruments'])
            quotes_map = cast(dict[str, dict[str, Any]], data['quotes']) if isinstance(data.get('quotes'), dict) else {}
            for inst in inst_list:
                sym_val = inst.get('tradingsymbol')
                sym: str | None = sym_val if isinstance(sym_val, str) else None
                q = quotes_map.get(sym) if sym is not None else None
                q = q if isinstance(q, dict) else {}
                merged.append({**inst, **q})
            with open(os.path.join(out_dir, 'merged.json'),'w') as f:
                json.dump({'index': index, 'expiry_tag': tag, 'records': merged}, f, indent=2)
    print("Mock universe generation complete.")

if __name__ == '__main__':
    main()
