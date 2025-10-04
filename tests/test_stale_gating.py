import datetime as dt
import os
import sys
import types
import pytest

from src.collectors.unified_collectors import run_unified_collectors

class _DummyProviders:
    def get_index_data(self, index):
        # Return a valid price so ATM path continues
        return 100.0, {'open':100,'high':101,'low':99,'close':100}
    def get_atm_strike(self, index):
        return 100.0
    def resolve_expiry(self, index, rule):
        return dt.date.today()
    def get_expiry_dates(self, index):
        return [dt.date.today()]
    def get_option_instruments(self, index, expiry_date, strikes):
        # Provide at least one instrument so option_count >0 (prevents early empty classification)
        out=[]
        for s in strikes:
            for t in ('CE','PE'):
                out.append({'tradingsymbol': f'{index}{int(s)}{t}','exchange':'NFO','instrument_type':t,'strike':s,'expiry':expiry_date})
        return out
    def get_option_instruments_universe(self, index):
        # Minimal universe so expiry map build path executes
        return []
    def enrich_with_quotes(self, instruments):
        # Return quotes with no fields except last_price missing -> simulate zero field coverage by omitting fields
        q={}
        for inst in instruments:
            sym=f"NFO:{inst['tradingsymbol']}"
            # Missing volume/oi/avg_price -> field coverage will be 0 (or treated missing)
            q[sym] = {'last_price': 1.0, 'strike': inst['strike'], 'instrument_type': inst['instrument_type']}
        return q
    def get_option_instruments_universe_cached(self, index):  # defensive (some code paths)
        return []

class _DummyCsvSink:
    def write_options_data(self, index_symbol, expiry_date, enriched_data, collection_time, **kw):
        # Return structure with minimal fields expected downstream
        return {'expiry_code':'WEEKLY','pcr':1.0,'timestamp':collection_time,'day_width':1}
    def write_overview_snapshot(self, *a, **k):
        # Should be skipped in skip mode (assert via flag)
        os.environ['G6__LAST_OVERVIEW_WRITE'] = '1'

@pytest.fixture
def providers():
    return _DummyProviders()

@pytest.fixture
def csv_sink(monkeypatch):
    # Remove sentinel before each test
    monkeypatch.delenv('G6__LAST_OVERVIEW_WRITE', raising=False)
    return _DummyCsvSink()

@pytest.fixture
def metrics():
    # Minimal namespace capturing attributes used in code
    return types.SimpleNamespace(collection_cycle_in_progress=types.SimpleNamespace(set=lambda *_: None))

_PARAMS = {"NIFTY": {"strikes_itm": 1, "strikes_otm": 1, "expiries": ["this_week"]}}

@pytest.mark.parametrize("mode", ["mark","skip"])
@pytest.mark.timeout(10)
def test_stale_index_modes_mark_and_skip(monkeypatch, providers, csv_sink, metrics, mode):
    monkeypatch.setenv('G6_STALE_FIELD_COV_THRESHOLD','0.2')  # anything <=0.2 is stale
    monkeypatch.setenv('G6_STALE_WRITE_MODE', mode)
    res = run_unified_collectors(_PARAMS, providers, csv_sink, None, metrics, build_snapshots=True)
    indices = res.get('indices') or []
    assert indices, 'expected an index entry'
    entry = indices[0]
    assert entry.get('status') == 'STALE', entry
    # In skip mode overview snapshot should not have been written
    wrote = os.getenv('G6__LAST_OVERVIEW_WRITE') == '1'
    if mode == 'skip':
        assert not wrote, 'overview write should be skipped in skip mode'
    else:
        assert wrote, 'overview write should occur in mark mode'

@pytest.mark.timeout(10)
def test_stale_abort(monkeypatch, providers, csv_sink, metrics):
    # Force abort after 2 consecutive stale cycles
    monkeypatch.setenv('G6_STALE_FIELD_COV_THRESHOLD','0.5')
    monkeypatch.setenv('G6_STALE_WRITE_MODE','abort')
    monkeypatch.setenv('G6_STALE_ABORT_CYCLES','2')
    # Run first cycle (should not exit)
    res1 = run_unified_collectors(_PARAMS, providers, csv_sink, None, metrics, build_snapshots=True)
    assert res1.get('indices')[0].get('status') == 'STALE'
    # Second cycle should trigger SystemExit with code 32
    with pytest.raises(SystemExit) as exc:
        run_unified_collectors(_PARAMS, providers, csv_sink, None, metrics, build_snapshots=True)
    assert exc.value.code == 32
