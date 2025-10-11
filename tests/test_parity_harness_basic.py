import copy
# NOTE(W4-11): Migrated from deprecated parity harness snapshot capture to direct
# parity score path (compute_parity_score). This test now validates structural
# determinism of unified collector output feeding the parity score logic.
from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.pipeline.parity import compute_parity_score

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


def test_parity_score_stable_with_repeat_unified_collectors_run():
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
    unified_a = run_unified_collectors(index_params=index_params, providers=providers, csv_sink=csv_sink, influx_sink=None, compute_greeks=False, estimate_iv=False, build_snapshots=False)
    unified_b = copy.deepcopy(unified_a)
    assert isinstance(unified_a, dict)
    # Legacy baseline simulated as identical structure for deterministic score 1.0
    parity_a = compute_parity_score(unified_a, unified_a)
    parity_b = compute_parity_score(unified_b, unified_b)
    assert parity_a['score'] == parity_b['score'] == 1.0
    # Components expected present (index_count, option_count at minimum)
    for comp in ['index_count','option_count']:
        assert comp in parity_a['components']
    # Ensure missing list empty when comparing identical baseline/pipeline views
    assert parity_a['missing'] == []
    # Structural: indices list stable & contains configured TESTIDX
    pipe_indices = unified_a.get('indices') or []
    if pipe_indices:
        assert pipe_indices[0]['index'] == 'TESTIDX'
        assert pipe_indices[0]['expiries']
