import os
import types
from typing import Any, Iterable

from src.collectors.unified_collectors import run_unified_collectors


class _DummyCsvSink:
    def write_options_data(self, *a, **k):
        return None
    def write_overview_snapshot(self, *a, **k):
        return None


class _DummyInflux:
    def write_overview_snapshot(self, *a, **k):
        return None

class DummyProviders:
    def __init__(self, instrument_count: int):
        self.instrument_count = instrument_count
    def get_index_data(self, index_symbol: str):
        # Return (index_price, ohlc_dict)
        return 20000.0, {'open':19950,'high':20100,'low':19800,'close':19990}
    def get_expiry_dates(self, index_symbol: str):  # minimal
        import datetime
        today = datetime.date.today()
        return [today]
    def resolve_expiry(self, index_symbol: str, rule: str):
        import datetime
        return datetime.date.today()
    def get_option_instruments(self, index_symbol: str, expiry_date: Any, strikes: Iterable[int]):
        # Simulate provider returning pre-expanded list that already filtered by strikes.
        # We'll attach two legs (CE/PE) per synthetic strike id until reaching instrument_count.
        base = int(min(strikes)) if strikes else 10000
        instruments: list[dict[str,Any]] = []
        i = 0
        while len(instruments) < self.instrument_count:
            strike_val = base + (i * 50)
            instruments.append({'tradingsymbol': f'SYM{i}CE', 'strike': strike_val, 'instrument_type': 'CE'})
            if len(instruments) >= self.instrument_count:
                break
            instruments.append({'tradingsymbol': f'SYM{i}PE', 'strike': strike_val, 'instrument_type': 'PE'})
            i += 1
        return instruments
    def get_atm_strike(self, index_symbol: str):
        return 20000
    def enrich_with_quotes(self, instruments):
        # Return quote dict keyed by synthetic symbol for unified_collectors expectation
        out = {}
        for inst in instruments:
            sym = inst.get('tradingsymbol') or inst.get('symbol') or f"S:{inst['strike']}{inst.get('instrument_type','') }"
            out[sym] = {
                'last_price':1.0,
                'volume':10,
                'oi':5,
                'avg_price':1.0,
                'strike':inst['strike'],
                'instrument_type':inst.get('instrument_type','')
            }
        return out


def _run_cycle(instrument_count: int, env: dict[str,str]) -> dict:
    # Patch os.environ temporarily
    old = {}
    for k,v in env.items():
        old[k] = os.environ.get(k)
        os.environ[k] = v
    try:
        providers = DummyProviders(instrument_count)
        params = { 'NIFTY': { 'expiries': ['this_week'], 'strikes_itm': 5, 'strikes_otm': 5 } }
        csv_sink = _DummyCsvSink()
        influx = None  # keep None to simplify
        result = run_unified_collectors(
            index_params=params,
            providers=providers,
            csv_sink=csv_sink,
            influx_sink=influx,
            compute_greeks=False,
            estimate_iv=False,
            build_snapshots=False,
        )
        # If index processing failed, surface debug info
        assert 'indices' in result, "run_unified_collectors did not return indices key"
        return result
    finally:
        for k in env:
            if old[k] is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old[k]


def test_no_clamp_when_under_threshold():
    env = {'G6_PREFILTER_MAX_INSTRUMENTS': '120', 'G6_FORCE_MARKET_OPEN': '1'}
    out = _run_cycle(100, env)
    exp = out['indices'][0]['expiries'][0]
    assert 'prefilter_clamped' not in exp
    assert exp['instruments'] == 100  # provider produced exactly 100 instruments


def test_clamp_triggers_and_truncates():
    env = {'G6_PREFILTER_MAX_INSTRUMENTS': '120', 'G6_FORCE_MARKET_OPEN': '1'}
    out = _run_cycle(300, env)
    exp = out['indices'][0]['expiries'][0]
    assert exp['prefilter_clamped'] is True
    assert exp['instruments'] == 120
    assert exp['prefilter_dropped'] == 180


def test_disable_flag_bypasses_clamp():
    env = {'G6_PREFILTER_MAX_INSTRUMENTS': '80', 'G6_PREFILTER_DISABLE': '1', 'G6_FORCE_MARKET_OPEN': '1'}
    out = _run_cycle(200, env)
    exp = out['indices'][0]['expiries'][0]
    assert 'prefilter_clamped' not in exp
    # Instruments should reflect full provider output (>= strikes *2 maybe truncated by strike match). We asserted clamp not applied.
    assert exp['instruments'] == 200


def test_strict_mode_sets_partial_reason():
    env = {'G6_PREFILTER_MAX_INSTRUMENTS': '60', 'G6_PREFILTER_CLAMP_STRICT': '1', 'G6_FORCE_MARKET_OPEN': '1'}
    out = _run_cycle(150, env)
    exp = out['indices'][0]['expiries'][0]
    assert exp['prefilter_clamped'] is True
    # Status may be recomputed later; ensure partial_reason seeded
    assert exp.get('partial_reason') == 'prefilter_clamp'

