import os, datetime
from types import SimpleNamespace

from src.collectors.unified_collectors import run_unified_collectors
from src.collectors.modules.pipeline import run_pipeline

class DeterministicProvider(SimpleNamespace):
    """Provider exposing methods used by both legacy and pipeline paths.

    Methods:
      - get_atm_strike(index_symbol)
      - resolve_expiry(index_symbol, rule)
      - get_option_instruments(index_symbol, expiry_date, strikes)
      - enrich_with_quotes(instruments)
    """
    def __init__(self, base_atm: int = 20000):
        super().__init__()
        self.base_atm = base_atm

    def get_atm_strike(self, index_symbol):
        return float(self.base_atm)

    def resolve_expiry(self, index_symbol, rule):
        # simple mapping: this_week -> today, next_week -> today+7
        today = datetime.date.today()
        if rule == 'this_week':
            return today
        if rule == 'next_week':
            return today + datetime.timedelta(days=7)
        return today

    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        instruments = []
        # Build CE/PE around each strike with fields expected by legacy validation
        for s in strikes:
            instruments.append({
                'strike': float(s),
                'instrument_type': 'CE',
                'tradingsymbol': f"{index_symbol}C{s}",
                'expiry_date': expiry_date,
            })
            instruments.append({
                'strike': float(s),
                'instrument_type': 'PE',
                'tradingsymbol': f"{index_symbol}P{s}",
                'expiry_date': expiry_date,
            })
        return instruments

    def enrich_with_quotes(self, instruments):
        out = {}
        for inst in instruments:
            ts = inst.get('tradingsymbol') or f"{inst['instrument_type']}{inst['strike']}"
            strike = float(inst['strike'])
            out[ts] = {
                'strike': strike,
                'instrument_type': inst['instrument_type'],
                'last_price': strike / 100.0,
                'bid': strike / 100.0 - 1,
                'ask': strike / 100.0 + 1,
                'oi': 10,
            }
        return out


def _run_legacy(index_params, providers):
    os.environ.pop('G6_PIPELINE_COLLECTOR', None)
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    return run_unified_collectors(index_params, providers, csv_sink=None, influx_sink=None, metrics=None, build_snapshots=False)


def _run_pipeline(index_params, providers):
    os.environ['G6_PIPELINE_COLLECTOR'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    return run_unified_collectors(index_params, providers, csv_sink=None, influx_sink=None, metrics=None, build_snapshots=False)


def normalize(res):
    # Keep a subset of fields for comparison that should already be stable.
    subset = {
        'indices_processed': res.get('indices_processed'),
        'index_summaries': []
    }
    for ix in res.get('indices', []):
        option_count = ix.get('option_count')
        exp_list = ix.get('expiries') or []
        # Count only expiries with >0 options for parity; legacy may drop empty expiry entries entirely
        expiry_count = 0
        for ex in exp_list:
            try:
                if (ex.get('options') or 0) > 0:
                    expiry_count += 1
            except Exception:
                pass
        subset['index_summaries'].append({
            'index': ix.get('index'),
            'status': ix.get('status'),
            'option_count': option_count,
            'expiry_count': expiry_count,
        })
    # Sort indices list for deterministic compare
    subset['index_summaries'] = sorted(subset['index_summaries'], key=lambda x: x['index'])
    return subset


def test_pipeline_parity_basic():
    index_params = {
        'NIFTY': {
            'symbol': 'NIFTY',
            'expiries': ['this_week'],
            'strikes_itm': 2,
            'strikes_otm': 2,
        }
    }
    prov = DeterministicProvider()
    # Isolate env side-effects
    prev_pipeline = os.environ.get('G6_PIPELINE_COLLECTOR')
    prev_force_open = os.environ.get('G6_FORCE_MARKET_OPEN')
    try:
        legacy = _run_legacy(index_params, prov)
        pipeline = _run_pipeline(index_params, prov)
    finally:
        # Restore prior environment
        if prev_pipeline is None:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        else:
            os.environ['G6_PIPELINE_COLLECTOR'] = prev_pipeline
        if prev_force_open is None:
            os.environ.pop('G6_FORCE_MARKET_OPEN', None)
        else:
            os.environ['G6_FORCE_MARKET_OPEN'] = prev_force_open
    assert isinstance(legacy, dict) and isinstance(pipeline, dict), "Both paths must produce structured dicts"
    n_legacy = normalize(legacy)
    n_pipeline = normalize(pipeline)
    # Assert stable subset parity
    assert n_legacy == n_pipeline
