import datetime as dt
from types import SimpleNamespace

from src.collectors.unified_collectors import run_unified_collectors

class DummyProviders:
    def get_index_data(self, index):
        return 100.0, {'open':100,'high':101,'low':99,'close':100}
    def get_atm_strike(self, index):
        return 100.0
    def resolve_expiry(self, index, rule):
        return dt.date.today()
    def get_expiry_dates(self, index):
        return [dt.date.today()]
    def get_option_instruments(self, index, expiry_date, strikes):
        out = []
        for s in strikes:
            for t in ('CE','PE'):
                out.append({'tradingsymbol': f'{index}{int(s)}{t}', 'exchange':'NFO', 'instrument_type': t, 'strike': s, 'expiry': expiry_date})
        return out
    def enrich_with_quotes(self, instruments):
        q = {}
        for inst in instruments:
            sym = f"NFO:{inst['tradingsymbol']}"
            q[sym] = {'last_price':1.0,'volume':10,'oi':5,'avg_price':1.0,'strike':inst['strike'],'instrument_type':inst['instrument_type']}
        return q

class DummyCsvSink:
    def write_options_data(self, index_symbol, expiry_date, enriched_data, collection_time, **kw):
        return {'expiry_code':'WEEKLY','pcr':1.0,'timestamp':collection_time,'day_width':1}
    def write_overview_snapshot(self, *a, **k):
        pass

def test_unified_collectors_structured_return(monkeypatch):
    params = {"NIFTY": {"strikes_itm": 1, "strikes_otm": 1, "expiries": ["this_week"]}}
    providers = DummyProviders()
    csv_sink = DummyCsvSink()
    influx_sink = None
    metrics = SimpleNamespace(collection_cycle_in_progress=SimpleNamespace(set=lambda *_: None))
    result = run_unified_collectors(params, providers, csv_sink, influx_sink, metrics, build_snapshots=True)
    assert isinstance(result, dict)
    assert result.get('status') == 'ok'
    assert result.get('indices_processed') == 1
    indices = result.get('indices')
    assert isinstance(indices, list) and len(indices) == 1
    idx_entry = indices[0]
    assert idx_entry['index'] == 'NIFTY'
    assert idx_entry['option_count'] > 0
    assert idx_entry['expiries'] and isinstance(idx_entry['expiries'], list)
    exp = idx_entry['expiries'][0]
    assert exp['rule'] == 'this_week'
    # Snapshot objects present
    if result.get('snapshots') is not None:
        assert result['snapshot_count'] == len(result['snapshots'])
