import copy
import datetime
from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.parity_harness import capture_parity_snapshot

# Reusable dummy provider supporting multiple indices and multiple expiries
class _ProvMulti:
    def __init__(self):
        self._ltp = 150.0
        self._expiries = [datetime.date.today(), datetime.date.today() + datetime.timedelta(days=7)]
    def get_index_data(self, index):
        return self._ltp, {}
    def get_atm_strike(self, index):
        return int(self._ltp)
    def get_ltp(self, index):
        return self._ltp
    def get_expiry_dates(self, index):
        return list(self._expiries)
    def get_option_instruments(self, index, expiry_date, strikes):
        out = []
        for s in strikes:
            out.append({'symbol': f"{index}-{expiry_date}-{int(s)}-CE", 'strike': s, 'instrument_type': 'CE'})
            out.append({'symbol': f"{index}-{expiry_date}-{int(s)}-PE", 'strike': s, 'instrument_type': 'PE'})
        return out
    def enrich_with_quotes(self, instruments):
        data = {}
        for inst in instruments:
            base_oi = 5 if inst['symbol'].startswith('BETA2') else 7
            data[inst['symbol']] = {
                'oi': base_oi,
                'instrument_type': inst['instrument_type'],
                'strike': inst['strike'],
                'expiry': None,
            }
        return data

class _CsvNull:
    def write_options_data(self, *a, **kw):
        return
    def write_overview_snapshot(self, *a, **kw):
        return


def _run(indices_conf):
    providers = _ProvMulti()
    csv_sink = _CsvNull()
    # build_snapshots False to keep harness focused on structural listing
    return run_unified_collectors(index_params=indices_conf, providers=providers, csv_sink=csv_sink, influx_sink=None, compute_greeks=False, estimate_iv=False, build_snapshots=False)


def test_parity_harness_multi_index_and_expiry_stability():
    import os
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    index_params = {
        'ALPHA': {
            'enable': True,
            'expiries': ['this_week', 'next_week'],  # exercise multiple rule codes (mapped to date list)
            'strikes_itm': 1,
            'strikes_otm': 1,
        },
        'BETA2': {
            'enable': True,
            'expiries': ['this_week'],
            'strikes_itm': 1,
            'strikes_otm': 2,
        }
    }
    result = _run(index_params)
    snap1 = capture_parity_snapshot(result)  # type: ignore[arg-type]
    # Deep copy to ensure deterministic reconstruction
    snap2 = capture_parity_snapshot(copy.deepcopy(result))  # type: ignore[arg-type]
    assert snap1.get('hash') == snap2.get('hash'), 'Deprecated hash placeholder should be stable'

    # Indices sorted alphabetically
    indices = [i['index'] for i in snap1['indices']]
    assert indices == sorted(indices)

    # Ensure each index captured with at least one expiry entry
    for idx in snap1['indices']:
        assert idx['expiries'], f"Index {idx['index']} missing expiries in parity snapshot"

    # Option counts should be positive and deterministic within snapshot
    option_counts = [idx['option_count'] for idx in snap1['indices']]
    assert all(isinstance(c, int) and c > 0 for c in option_counts)

    # PCR presence (may be empty dict but key should exist)
    assert 'pcr' in snap1
