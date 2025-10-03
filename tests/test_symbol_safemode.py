import os
import datetime

from src.broker.kite_provider import KiteProvider

EXPIRY = datetime.date(2025, 9, 30)


class LegacyDummy(KiteProvider):
    def __init__(self):
        self._option_instrument_cache = {}
        self._option_cache_day = datetime.date.today().isoformat()
        self._option_cache_hits = 0
        self._option_cache_misses = 0
        self._used_fallback = False
    def get_instruments(self, exchange=None):
        return [
            {"tradingsymbol": "NIFTY25SEP25000CE", "instrument_type": "CE", "expiry": EXPIRY, "strike": 25000},
            {"tradingsymbol": "FINNIFTY25SEP25000CE", "instrument_type": "CE", "expiry": EXPIRY, "strike": 25000},
        ]
    def get_expiry_dates(self, index_symbol):
        return [EXPIRY]


def test_legacy_mode_with_safemode_blocks_contamination():
    os.environ['G6_SYMBOL_MATCH_MODE'] = 'legacy'
    os.environ['G6_SYMBOL_MATCH_SAFEMODE'] = '1'
    prov = LegacyDummy()
    res = prov.option_instruments('NIFTY', EXPIRY, [25000])
    syms = {r['tradingsymbol'] for r in res}
    assert syms == {"NIFTY25SEP25000CE"}

def test_legacy_mode_without_safemode_still_blocks_due_to_root_gate():
    os.environ['G6_SYMBOL_MATCH_MODE'] = 'legacy'
    os.environ['G6_SYMBOL_MATCH_SAFEMODE'] = '0'
    prov = LegacyDummy()
    res = prov.option_instruments('NIFTY', EXPIRY, [25000])
    syms = {r['tradingsymbol'] for r in res}
    assert syms == {"NIFTY25SEP25000CE"}