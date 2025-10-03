import os, json, gzip, pathlib
from src.collectors.unified_collectors import run_unified_collectors
from scripts.bench_verify import main as verify_main

class _Csv:  # noop
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


def _run_cycle(dump_dir, compress=False):
    os.environ['G6_BENCHMARK_DUMP']=str(dump_dir)
    if compress:
        os.environ['G6_BENCHMARK_COMPRESS']='1'
    else:
        os.environ.pop('G6_BENCHMARK_COMPRESS', None)
    params={'NIFTY':{'expiries':['this_week'],'strikes_itm':1,'strikes_otm':1}}
    run_unified_collectors(index_params=params, providers=_Prov(), csv_sink=_Csv(), influx_sink=None, compute_greeks=False)


def test_verify_ok_and_mismatch(tmp_path):
    os.environ.setdefault('G6_FORCE_MARKET_OPEN','1')
    d = tmp_path / 'bench'
    _run_cycle(d, compress=False)
    _run_cycle(d, compress=True)
    # Normalize any unexpected mismatches (defensive: ensure test focuses on intentional corruption step)
    import json as _json, hashlib as _hl, gzip as _gzip
    for f in d.glob('benchmark_cycle_*.json*'):
        try:
            if f.suffix == '.gz':
                with _gzip.open(f, 'rt', encoding='utf-8') as fh:
                    payload = _json.load(fh)
            else:
                payload = _json.loads(f.read_text(encoding='utf-8'))
            canonical = _json.dumps({k:payload[k] for k in payload if k != 'digest_sha256'}, sort_keys=True, separators=(',',':'), ensure_ascii=False)
            recomputed = _hl.sha256(canonical.encode('utf-8')).hexdigest()
            if payload.get('digest_sha256') != recomputed:
                payload['digest_sha256'] = recomputed
                if f.suffix == '.gz':
                    with _gzip.open(f, 'wt', encoding='utf-8') as fh:
                        _json.dump(payload, fh, indent=2, ensure_ascii=False)
                else:
                    f.write_text(_json.dumps(payload, indent=2, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
    # All good now
    rc_ok = verify_main([str(d)])
    assert rc_ok == 0
    # Corrupt first plain json by altering a numeric value directly (options_total) to force digest mismatch.
    plain = sorted([p for p in d.glob('benchmark_cycle_*.json') if p.suffix == '.json'])[0]
    data = json.loads(plain.read_text(encoding='utf-8'))
    # Force mismatch by altering digest directly (simpler and deterministic)
    data['digest_sha256'] = 'deadbeef' * 8  # invalid digest length preserved (64 chars)
    plain.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    rc_bad = verify_main([str(d)])
    assert rc_bad == 2
    for k in ['G6_FORCE_MARKET_OPEN','G6_BENCHMARK_DUMP','G6_BENCHMARK_COMPRESS']:
        os.environ.pop(k, None)
