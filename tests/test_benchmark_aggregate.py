import os, json, csv, gzip
from pathlib import Path
from src.collectors.unified_collectors import run_unified_collectors

class _Csv:  # noop sink
    def write_options_data(self,*a,**k): return None
    def write_overview_snapshot(self,*a,**k): return None

class _Prov:
    def get_index_data(self, index_symbol):
        return 20000.0, {'open':19900,'high':20100,'low':19800,'close':19950}
    def get_expiry_dates(self, index_symbol):
        import datetime; return [datetime.date.today()]
    def resolve_expiry(self, index_symbol, rule):
        import datetime; return datetime.date.today()
    def get_option_instruments(self, index_symbol, expiry_date, strikes):
        out=[]
        for s in strikes:
            out.append({'tradingsymbol':f'C{s}','strike':s,'instrument_type':'CE'})
            out.append({'tradingsymbol':f'P{s}','strike':s,'instrument_type':'PE'})
        return out
    def get_atm_strike(self, index_symbol):
        return 20000
    def enrich_with_quotes(self, instruments):
        return {i['tradingsymbol']:{'strike':i['strike'],'instrument_type':i['instrument_type'],'oi':10,'last_price':1.0} for i in instruments}


def _run_cycle(dump_dir):
    os.environ['G6_BENCHMARK_DUMP']=str(dump_dir)
    params={'NIFTY':{'expiries':['this_week'],'strikes_itm':1,'strikes_otm':1}}
    run_unified_collectors(index_params=params, providers=_Prov(), csv_sink=_Csv(), influx_sink=None, compute_greeks=False)


def test_bench_aggregate_basic(tmp_path):
    os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
    dump_dir = tmp_path / 'bench'
    import time
    for i in range(2):
        _run_cycle(dump_dir)
        if i == 0:
            time.sleep(0.002)  # ensure distinct timestamp
    out_csv = tmp_path / 'out.csv'
    from scripts.bench_aggregate import main as agg_main
    agg_main(['--dir', str(dump_dir), '--out', str(out_csv)])
    text = out_csv.read_text(encoding='utf-8').splitlines()
    assert text, 'CSV should not be empty'
    header = text[0].split(',')
    assert 'options_total' in header
    assert any(h.startswith('phase_') for h in header)
    rows = text[1:]
    assert len(rows) >= 2, rows


def test_bench_aggregate_with_index_breakdown(tmp_path):
    os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
    dump_dir = tmp_path / 'bench'
    _run_cycle(dump_dir)
    out_csv = tmp_path / 'out_idx.csv'
    from scripts.bench_aggregate import main as agg_main
    agg_main(['--dir', str(dump_dir), '--out', str(out_csv), '--include-index-breakdown'])
    header = out_csv.read_text(encoding='utf-8').splitlines()[0].split(',')
    assert any(h.startswith('per_index_NIFTY_') for h in header)

    for k in ['G6_FORCE_MARKET_OPEN','G6_BENCHMARK_DUMP']:
        os.environ.pop(k, None)
