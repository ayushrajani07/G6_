import datetime

from src.broker.kite_provider import KiteProvider

class DummyInstrumentsProvider(KiteProvider):
    def __init__(self):
        # Bypass real init
        self._option_instrument_cache = {}
        self._option_cache_day = datetime.date.today().isoformat()
        self._option_cache_hits = 0
        self._option_cache_misses = 0
        self._used_fallback = False
    def get_instruments(self, exchange=None):  # minimal fixture
        expiry = datetime.date(2025, 9, 30)
        return [
            {"tradingsymbol": "NIFTY25SEP25000CE", "instrument_type": "CE", "expiry": expiry, "strike": 25000},
            {"tradingsymbol": "NIFTY25SEP25000PE", "instrument_type": "PE", "expiry": expiry, "strike": 25000},
            # Contaminant FINNIFTY symbols which previously slipped in
            {"tradingsymbol": "FINNIFTY25SEP25000CE", "instrument_type": "CE", "expiry": expiry, "strike": 25000},
            {"tradingsymbol": "FINNIFTY25SEP25000PE", "instrument_type": "PE", "expiry": expiry, "strike": 25000},
        ]
    def get_expiry_dates(self, index_symbol):
        return [datetime.date(2025, 9, 30)]


def test_strict_symbol_filter_excludes_finnifty():
    kp = DummyInstrumentsProvider()
    expiry = datetime.date(2025, 9, 30)
    strikes = [25000]
    res = kp.option_instruments("NIFTY", expiry, strikes)
    syms = {r["tradingsymbol"] for r in res}
    assert syms == {"NIFTY25SEP25000CE", "NIFTY25SEP25000PE"}, syms
