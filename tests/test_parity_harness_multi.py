import copy
# NOTE(W4-11): Migrated off deprecated parity harness. This test now validates
# parity score component behavior (index_count, option_count) under structural
# differences between legacy baseline and pipeline views.
import datetime
from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.pipeline.parity import compute_parity_score

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


def test_parity_score_degrades_when_index_missing():
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
    unified_full = _run(index_params)
    assert isinstance(unified_full, dict)
    # Sanity shape (indices sorted behavior preserved)
    full_indices = unified_full['indices'] if isinstance(unified_full.get('indices'), list) else []  # type: ignore[index]
    indices = [i['index'] for i in full_indices]
    assert indices == sorted(indices) and indices, 'Expected non-empty sorted indices'

    # Full parity (baseline == pipeline) => score 1.0
    full_score = compute_parity_score(unified_full, unified_full)
    assert full_score['score'] == 1.0
    assert full_score['components']['index_count'] == 1.0
    assert full_score['components']['option_count'] == 1.0

    # Remove one index from pipeline view -> degraded parity
    degraded_pipeline = copy.deepcopy(unified_full)
    pipe_indices = degraded_pipeline['indices'] if isinstance(degraded_pipeline.get('indices'), list) else []  # type: ignore[index]
    degraded_pipeline['indices'] = [i for i in pipe_indices if isinstance(i, dict) and i.get('index') != 'BETA2']
    degraded_score = compute_parity_score(unified_full, degraded_pipeline)
    assert 0 < degraded_score['score'] < 1.0
    assert degraded_score['components']['index_count'] < 1.0
    assert degraded_score['components']['option_count'] < 1.0
    # Missing list may be empty depending on component diff semantics; primary
    # assertion is that score and component weights degrade.
    assert degraded_score['score'] < full_score['score']
