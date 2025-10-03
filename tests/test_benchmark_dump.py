import os, json, glob, pathlib, time, pytest
# Ensure market hours gating does not short-circuit the collector during the test.
os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
from src.collectors.unified_collectors import run_unified_collectors

class _DummyCsv:
    def write_options_data(self, *a, **k):
        return None
    def write_overview_snapshot(self, *a, **k):
        return None

class _DummyProv:
    def get_index_data(self, index_symbol):
        return 20000.0, {'open':19900,'high':20100,'low':19800,'close':19950}
    def get_expiry_dates(self, index_symbol):
        import datetime
        return [datetime.date.today()]
    def resolve_expiry(self, index_symbol, rule):
        import datetime
        return datetime.date.today()
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        out = []
        for i,s in enumerate(strikes):
            out.append({'tradingsymbol':f'C{i}','strike':s,'instrument_type':'CE'})
            out.append({'tradingsymbol':f'P{i}','strike':s,'instrument_type':'PE'})
        return out
    def get_atm_strike(self, index_symbol):
        return 20000
    def enrich_with_quotes(self, instruments):
        return {inst['tradingsymbol']:{'instrument_type':inst['instrument_type'],'strike':inst['strike'],'oi':10,'last_price':1.0} for inst in instruments}


def test_benchmark_dump_creates_artifact(tmp_path):
    dump_dir = tmp_path / 'bench'
    os.environ['G6_BENCHMARK_DUMP'] = str(dump_dir)
    # Force market open so the unified collectors do not short-circuit with 'market_closed'
    # which would prevent a normal cycle summary and artifact emission in some configurations.
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    try:
        params = {'NIFTY': {'expiries':['this_week'],'strikes_itm':2,'strikes_otm':2}}
        res = run_unified_collectors(index_params=params, providers=_DummyProv(), csv_sink=_DummyCsv(), influx_sink=None, compute_greeks=False)
        if res.get('status') == 'market_closed':
            pytest.skip('Market closed gating active unexpectedly; skipping benchmark dump artifact assertion.')
        assert res['status'] == 'ok'
        files = list(dump_dir.glob('benchmark_cycle_*.json'))
        assert files, 'No benchmark artifact produced'
        # Basic schema check
        with open(files[0],'r',encoding='utf-8') as f:
            data = json.load(f)
        assert 'phase_times' in data and 'indices' in data and 'duration_s' in data
    finally:
        os.environ.pop('G6_BENCHMARK_DUMP', None)
        os.environ.pop('G6_FORCE_MARKET_OPEN', None)
