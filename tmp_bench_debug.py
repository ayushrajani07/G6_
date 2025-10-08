import tempfile, subprocess, sys, json, pathlib, os
from src.collectors.unified_collectors import run_unified_collectors
class _Csv:
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
 def get_atm_strike(self, index_symbol): return 20000
 def enrich_with_quotes(self, instruments):
  return {i['tradingsymbol']:{'strike':i['strike'],'instrument_type':i['instrument_type'],'oi':10,'last_price':1.0} for i in instruments}

tmpdir = pathlib.Path(tempfile.mkdtemp())/ 'bench'
tmpdir.mkdir(parents=True, exist_ok=True)
os.environ['G6_FORCE_MARKET_OPEN']='1'
os.environ['G6_BENCHMARK_DUMP']=str(tmpdir)
os.environ['G6_BENCHMARK_ANNOTATE_OUTLIERS']='1'
params={'NIFTY':{'expiries':['this_week'],'strikes_itm':1,'strikes_otm':1}}
for _ in range(5):
 run_unified_collectors(index_params=params, providers=_Prov(), csv_sink=_Csv(), influx_sink=None, compute_greeks=False)
print('Artifacts generated:', len(list(tmpdir.glob('benchmark_cycle_*.json'))))
a=sorted(tmpdir.glob('benchmark_cycle_*.json'))[-1]
print('Last artifact path:', a)
print('Last artifact content snippet:', a.read_text()[:200])
# mutate
import json as _json
data=_json.loads(a.read_text())
data['options_total']= (data.get('options_total') or 0)*10 + 500
data.pop('anomalies', None)
(a.parent / (a.stem + '_synthetic.json')).write_text(_json.dumps(data), encoding='utf-8')
print('Artifacts after synthetic:', len(list(tmpdir.glob('benchmark_cycle_*.json'))))
out = subprocess.check_output([sys.executable,'scripts/bench_trend.py','--dir',str(tmpdir),'--limit','20','--compute-anomalies'], text=True)
print('TREND_OUTPUT_START')
print(repr(out))
print(out)
print('TREND_OUTPUT_END')
