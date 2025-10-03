import os, json, gzip, time, pathlib
from src.collectors.unified_collectors import run_unified_collectors

class _DummyCsv:
    def write_options_data(self, *a, **k):
        return None
    def write_overview_snapshot(self, *a, **k):
        return None

class _Prov:
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
        for s in strikes:
            out.append({'tradingsymbol':f'C{s}','strike':s,'instrument_type':'CE'})
            out.append({'tradingsymbol':f'P{s}','strike':s,'instrument_type':'PE'})
        return out
    def get_atm_strike(self, index_symbol):
        return 20000
    def enrich_with_quotes(self, instruments):
        return {i['tradingsymbol']:{'strike':i['strike'],'instrument_type':i['instrument_type'],'oi':10,'last_price':1.0} for i in instruments}


def _run_cycle(params):
    return run_unified_collectors(index_params=params, providers=_Prov(), csv_sink=_DummyCsv(), influx_sink=None, compute_greeks=False)


def test_benchmark_dump_compress_and_retention(tmp_path):
    # Force market open to avoid gating during off-hours
    os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
    dump_dir = tmp_path / 'bench'
    os.environ['G6_BENCHMARK_DUMP'] = str(dump_dir)
    os.environ['G6_BENCHMARK_COMPRESS'] = '1'
    os.environ['G6_BENCHMARK_KEEP_N'] = '3'
    try:
        params = {'NIFTY': {'expiries':['this_week'],'strikes_itm':1,'strikes_otm':1}}
        # Produce more cycles than retention limit
        for _ in range(5):
            _run_cycle(params)
            # ensure distinct timestamp granularity (at least 1 second) if clock coarse
            time.sleep(0.01)
        all_files = sorted(dump_dir.glob('benchmark_cycle_*.json.gz'))
        assert all_files, 'No compressed benchmark artifacts produced'
        # Retention should prune to <= keep_n
        assert len(all_files) <= 3, f'Retention did not prune old artifacts (have {len(all_files)})'
        # Basic schema validation on newest file
        newest = all_files[-1]
        with gzip.open(newest, 'rt', encoding='utf-8') as f:
            data = json.load(f)
        assert data.get('version') == 1 and 'phase_times' in data and 'indices' in data
    finally:
        for k in ['G6_BENCHMARK_DUMP','G6_BENCHMARK_COMPRESS','G6_BENCHMARK_KEEP_N','G6_FORCE_MARKET_OPEN']:
            os.environ.pop(k, None)
