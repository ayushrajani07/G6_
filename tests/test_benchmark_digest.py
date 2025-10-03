import os, json, gzip, pathlib
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


def test_benchmark_artifact_has_digest_and_options(tmp_path):
    os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
    dump_dir = tmp_path / 'bench'
    os.environ['G6_BENCHMARK_DUMP'] = str(dump_dir)
    try:
        params={'NIFTY':{'expiries':['this_week'],'strikes_itm':1,'strikes_otm':1}}
        run_unified_collectors(index_params=params, providers=_Prov(), csv_sink=_Csv(), influx_sink=None, compute_greeks=False)
        f = next(iter(dump_dir.glob('benchmark_cycle_*.json')))
        data = json.loads(f.read_text(encoding='utf-8'))
        assert 'options_total' in data and isinstance(data['options_total'], (int,float))
        assert 'digest_sha256' in data and data['digest_sha256']
        # Ensure digest stable if we recompute canonical
        import hashlib, json as _json
        canonical = _json.dumps({k:data[k] for k in data if k != 'digest_sha256'}, sort_keys=True, separators=(',',':'), ensure_ascii=False)
        recomputed = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
        # Because original digest computed before insertion we emulate that by dropping digest key
        assert recomputed == data['digest_sha256']
    finally:
        for k in ['G6_FORCE_MARKET_OPEN','G6_BENCHMARK_DUMP']:
            os.environ.pop(k, None)
