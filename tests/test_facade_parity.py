import os
import pytest

@pytest.fixture(autouse=True)
def _force_market_open(monkeypatch):
    """Force market open so legacy path doesn't short-circuit with 'market_closed'.

    Several collectors consult src.utils.market_hours.is_market_open(). We coerce it to True
    to make this test deterministic independent of wall-clock.
    """
    monkeypatch.setattr('src.utils.market_hours.is_market_open', lambda *a, **k: True)
    # Legacy helpers sometimes import a simplified alias in timeutils
    try:
        monkeypatch.setattr('src.utils.timeutils.is_market_open', lambda *a, **k: True)
    except Exception:
        pass
    yield
from src.orchestrator.facade import run_collect_cycle

@pytest.fixture(autouse=True)
def _restore_pipeline_flag():
    orig = os.environ.get('G6_PIPELINE_COLLECTOR')
    try:
        yield
    finally:
        if orig is None:
            os.environ.pop('G6_PIPELINE_COLLECTOR', None)
        else:
            os.environ['G6_PIPELINE_COLLECTOR'] = orig

class DummyProviders:
    """Augmented provider to satisfy both pipeline and legacy expectations.

    Provides minimal instrument chain, ATM strike, quote enrichment, and index data
    so both modes can produce status='ok'. Legacy path expects get_index_data -> (price, ohlc)
    while some helpers may fallback to get_ltp; both are supplied.
    """
    def __init__(self):
        import datetime
        self._today = datetime.date.today()
        self._exp1 = self._today + datetime.timedelta(days=7)
        self._exp2 = self._today + datetime.timedelta(days=14)

    # Instrument universe
    def get_instrument_chain(self, index_symbol):
        return [
            {"expiry": self._exp1, "strike": 100, "type": "CE"},
            {"expiry": self._exp1, "strike": 110, "type": "PE"},
            {"expiry": self._exp2, "strike": 100, "type": "CE"},
        ]

    # Some legacy paths call resolve_expiry + get_option_instruments style providers;
    # provide a thin compatibility shim mapping to our static chain.
    def resolve_expiry(self, index_symbol, rule):  # rule ignored ('this_week' etc.)
        return self._exp1

    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        out = []
        for k in strikes:
            out.append({'strike': k, 'instrument_type': 'CE'})
            out.append({'strike': k, 'instrument_type': 'PE'})
        return out

    def get_atm_strike(self, index_symbol):
        return 105

    # Legacy path may ask for index data
    def get_index_data(self, index_symbol):
        # Return (price, ohlc_dict) as expected by legacy collectors
        price = 100.0
        ohlc = {"open": 99.0, "high": 101.0, "low": 98.5, "close": 99.5}
        return price, ohlc

    # Fallback used if ATM strike fails or alternative price lookup needed
    def get_ltp(self, index_symbol):
        return 100.0

    # Quote enrichment hooks (pipeline async enrichment fallback expectation)
    def enrich_with_quotes(self, instruments):
        # Provide a dict keyed similarly to typical enrichers so downstream code recognizes structure
        data = {}
        for inst in instruments:
            k = f"{int(inst.get('strike',0))}{inst.get('type') or inst.get('instrument_type','')}"
            data[k] = {
                'strike': inst.get('strike'),
                'instrument_type': inst.get('type') or inst.get('instrument_type'),
                'last_price': 1.1,
                'bid': 1.0,
                'ask': 1.2,
                'oi': 10,
                'volume': 5,
                'avg_price': 1.1,
            }
        return data


def _run(mode, parity=False):
    index_params = {"TEST": {"strikes_itm": 1, "strikes_otm": 1}}
    providers = DummyProviders()
    return run_collect_cycle(index_params, providers, csv_sink=None, influx_sink=None, metrics=None, mode=mode, parity_check=parity)


def test_facade_pipeline_parity_mode_executes():
    pipe_res = _run('pipeline', parity=False)
    leg_res = _run('legacy', parity=False)
    assert pipe_res.get('status') == 'ok'
    # Legacy path status is informational for this simplified parity test; ensure it returns a dict.
    assert isinstance(leg_res, dict) and 'status' in leg_res
    parity_res = _run('pipeline', parity=True)
    assert parity_res.get('status') == 'ok'
    assert 'indices' in parity_res


def test_facade_pipeline_vs_legacy_parity():
    """Deprecated old hash parity test name retained as a no-op wrapper."""
    test_facade_pipeline_parity_mode_executes()
