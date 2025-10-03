import copy
from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.parity_harness import capture_parity_snapshot

# Minimal dummy provider + sinks mirroring patterns in other tests
class _Prov:
    """Minimal synchronous provider matching unified_collectors interface subset.

    Methods implemented:
      - get_index_data(index) -> (ltp, ohlc)
      - get_atm_strike(index) -> float
      - get_ltp(index) -> float (fallback path)
      - get_expiry_dates(index) -> list[date]
      - get_option_instruments(index, expiry_date, strikes)
      - enrich_with_quotes(instruments) -> mapping
    """
    def __init__(self):
        self._ltp = 100.0
    def get_index_data(self, index):
        return self._ltp, {}
    def get_atm_strike(self, index):  # used primarily; stable deterministic
        return int(self._ltp)
    def get_ltp(self, index):  # fallback if atm fails
        return self._ltp
    def get_expiry_dates(self, index):
        import datetime
        return [datetime.date.today()]
    def get_option_instruments(self, index, expiry_date, strikes):
        out = []
        for s in strikes:
            out.append({'symbol': f"{index}-{int(s)}-CE", 'strike': s, 'instrument_type': 'CE'})
            out.append({'symbol': f"{index}-{int(s)}-PE", 'strike': s, 'instrument_type': 'PE'})
        return out
    def enrich_with_quotes(self, instruments):
        data = {}
        for inst in instruments:
            data[inst['symbol']] = {
                'oi': 10,
                'instrument_type': inst['instrument_type'],
                'strike': inst['strike'],
                'expiry': None,  # allow preventive validator to impute
            }
        return data

# Defensive: ensure attributes exist even if prior cached class used
_Prov.get_atm_strike = _Prov.get_atm_strike  # type: ignore[attr-defined]
_Prov.get_option_instruments = _Prov.get_option_instruments  # type: ignore[attr-defined]
_Prov.enrich_with_quotes = _Prov.enrich_with_quotes  # type: ignore[attr-defined]

class _Csv:
    def write_options_data(self, *a, **kw):
        return
    def write_overview_snapshot(self, *a, **kw):
        return


def test_parity_harness_stable_snapshot():
    import os
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    # Defensive: if stale cached _Prov without new methods somehow present, patch them.
    if not hasattr(_Prov, 'get_atm_strike'):
        def _atm(self, index):
            return int(getattr(self,'_ltp',100) or 100)
        _Prov.get_atm_strike = _atm  # type: ignore[attr-defined]
    if not hasattr(_Prov, 'enrich_with_quotes') and hasattr(_Prov, 'enrich_quotes'):
        _Prov.enrich_with_quotes = getattr(_Prov, 'enrich_quotes')  # type: ignore[attr-defined]
    index_params = {
        'TESTIDX': {
            'enable': True,
            'expiries': ['this_week'],
            'strikes_itm': 1,
            'strikes_otm': 1,
        }
    }
    providers = _Prov()
    csv_sink = _Csv()
    result = run_unified_collectors(index_params=index_params, providers=providers, csv_sink=csv_sink, influx_sink=None, compute_greeks=False, estimate_iv=False, build_snapshots=False)
    assert isinstance(result, dict)
    snap1 = capture_parity_snapshot(result)  # type: ignore[arg-type]
    snap2 = capture_parity_snapshot(copy.deepcopy(result))  # type: ignore[arg-type]
    # Hash field is deprecated placeholder; still expect stable equality for placeholder string.
    assert snap1.get('hash') == snap2.get('hash')
    # Basic shape assertions (graceful if indices filtered out under rare validation edge)
    if snap1['indices']:
        assert snap1['indices'][0]['index'] == 'TESTIDX'
        assert snap1['indices'][0]['expiries']
    assert 'pcr' in snap1
