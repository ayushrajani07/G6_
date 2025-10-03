import os
import importlib
import datetime

from src.utils.symbol_root import symbol_matches_index
from src.broker.kite_provider import KiteProvider

EXPIRY = datetime.date(2025, 9, 30)

class MultiIndexDummy(KiteProvider):
    def __init__(self):
        self._option_instrument_cache = {}
        self._option_cache_day = datetime.date.today().isoformat()
        self._option_cache_hits = 0
        self._option_cache_misses = 0
        self._used_fallback = False
    def get_instruments(self, exchange=None):  # minimal fixture
        return [
            {"tradingsymbol": "NIFTY25SEP25000CE", "instrument_type": "CE", "expiry": EXPIRY, "strike": 25000},
            {"tradingsymbol": "NIFTY25SEP25000PE", "instrument_type": "PE", "expiry": EXPIRY, "strike": 25000},
            {"tradingsymbol": "FINNIFTY25SEP25000CE", "instrument_type": "CE", "expiry": EXPIRY, "strike": 25000},
            {"tradingsymbol": "FINNIFTY25SEP25000PE", "instrument_type": "PE", "expiry": EXPIRY, "strike": 25000},
            {"tradingsymbol": "BANKNIFTY25SEP47000CE", "instrument_type": "CE", "expiry": EXPIRY, "strike": 47000},
        ]
    def get_expiry_dates(self, index_symbol):
        return [EXPIRY]


def _collect(index_symbol, mode):
    os.environ['G6_SYMBOL_MATCH_MODE'] = mode
    # Reload symbol_root to pick up env (mode read at import time for default); keep function call overrides explicit too.
    importlib.reload(__import__('src.utils.symbol_root', fromlist=['symbol_matches_index']))
    prov = MultiIndexDummy()
    return prov.option_instruments(index_symbol, EXPIRY, [25000, 47000])


def test_strict_mode_excludes_contaminants():
    res = _collect('NIFTY', 'strict')
    syms = {r['tradingsymbol'] for r in res}
    assert syms == {"NIFTY25SEP25000CE", "NIFTY25SEP25000PE"}


def test_legacy_mode_still_blocks_contamination_due_to_root_gate():
    os.environ['G6_SYMBOL_MATCH_SAFEMODE'] = '0'  # even with safemode off
    res = _collect('NIFTY', 'legacy')
    syms = {r['tradingsymbol'] for r in res}
    assert syms == {"NIFTY25SEP25000CE", "NIFTY25SEP25000PE"}


def test_explicit_symbol_matches_index_function():
    # spot checks for utility
    assert symbol_matches_index('NIFTY', 'NIFTY25SEP25000CE', mode='strict') is True
    assert symbol_matches_index('NIFTY', 'FINNIFTY25SEP25000CE', mode='strict') is False
    assert symbol_matches_index('NIFTY', 'FINNIFTY25SEP25000CE', mode='legacy') is True
    assert symbol_matches_index('BANKNIFTY', 'BANKNIFTY25SEP47000CE', mode='strict') is True
