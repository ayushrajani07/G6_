import os, json, pathlib, subprocess, sys
from src.collectors.unified_collectors import run_unified_collectors
from src.bench.anomaly import detect_anomalies, rolling_detect

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


def _run_cycle(dump_dir, annotate=False):
    os.environ['G6_FORCE_MARKET_OPEN']='1'
    os.environ['G6_BENCHMARK_DUMP']=str(dump_dir)
    if annotate:
        os.environ['G6_BENCHMARK_ANNOTATE_OUTLIERS']='1'
    else:
        os.environ.pop('G6_BENCHMARK_ANNOTATE_OUTLIERS', None)
    params={'NIFTY':{'expiries':['this_week'],'strikes_itm':1,'strikes_otm':1}}
    run_unified_collectors(index_params=params, providers=_Prov(), csv_sink=_Csv(), influx_sink=None, compute_greeks=False)


def test_detect_anomalies_basic():
    # Stable series then spike
    series = [100,101,99,100,102, 200]  # last point extreme
    flags, scores = detect_anomalies(series, threshold=3.5, min_points=5)
    assert len(flags)==len(series)
    assert flags[-1] is True, (flags, scores)


def test_rolling_detect():
    series = [100,101,99,100,200, 100,101]
    marks = rolling_detect(series, window=5, threshold=3.5, min_points=5)
    assert len(marks)==len(series)
    # The 5th element (value 200) should be flagged once enough history (first 4) then itself
    assert marks[4] is True


def test_artifact_anomaly_annotation(tmp_path):
    dump_dir = tmp_path / 'bench'
    # Produce baseline cycles (no spike) to build history
    for _ in range(5):
        _run_cycle(dump_dir, annotate=True)
    # Manually append an outlier artifact by simulating drastically higher options_total
    # Simplest: create a copy of last artifact and modify options_total; re-run detection disabled so not re-hashed.
    arts = sorted(dump_dir.glob('benchmark_cycle_*.json'))
    assert arts, 'expected artifacts'
    last = arts[-1]
    data = json.loads(last.read_text(encoding='utf-8'))
    data['options_total'] = (data.get('options_total') or 0) * 10 + 500
    # Remove digest to avoid confusion; this is synthetic abnormal artifact
    data.pop('digest_sha256', None)
    # Drop existing anomaly annotations so recompute path is exercised
    data.pop('anomalies', None)
    data.pop('anomaly_summary', None)
    synthetic = dump_dir / (last.stem + '_synthetic.json')
    synthetic.write_text(json.dumps(data, indent=2), encoding='utf-8')
    # Now run trend script with recompute to confirm anomaly is detected among last artifacts
    cmd = [sys.executable, 'scripts/bench_trend.py', '--dir', str(dump_dir), '--limit', '20', '--compute-anomalies']
    out = subprocess.check_output(cmd, text=True)
    # Expect at least one '!' flag in output (anomaly marker)
    assert '!' in out, out


def test_bench_report_smoke(tmp_path):
    dump_dir = tmp_path / 'bench'
    for _ in range(3):
        _run_cycle(dump_dir, annotate=True)
    cmd = [sys.executable, 'scripts/bench_report.py', '--dir', str(dump_dir), '--limit', '10']
    rep = subprocess.check_output(cmd, text=True)
    assert 'Benchmark Report' in rep
    assert 'options_total' in rep

    for k in ['G6_FORCE_MARKET_OPEN','G6_BENCHMARK_DUMP','G6_BENCHMARK_ANNOTATE_OUTLIERS']:
        os.environ.pop(k, None)
