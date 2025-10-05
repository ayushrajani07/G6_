import datetime as dt
import os
import types

from src.collectors.unified_collectors import run_unified_collectors

class _WeekendProviders:
    def get_index_data(self, index):
        return 100.0, {'open':100,'high':101,'low':99,'close':100}
    def get_atm_strike(self, index):
        return 100.0
    def resolve_expiry(self, index, rule):
        # Force a weekday date for consistency
        return dt.date.today()
    def get_expiry_dates(self, index):
        return [dt.date.today()]
    def get_option_instruments(self, index, expiry_date, strikes):
        instruments=[]
        for s in strikes:
            for t in ('CE','PE'):
                instruments.append({'tradingsymbol': f'{index}{int(s)}{t}','exchange':'NFO','instrument_type':t,'strike':s,'expiry':expiry_date})
        return instruments
    def enrich_with_quotes(self, instruments):
        # Provide quotes missing volume/oi/avg_price so field coverage -> 0
        out={}
        for inst in instruments:
            sym=f"NFO:{inst['tradingsymbol']}"
            out[sym] = {'last_price':1.0,'strike':inst['strike'],'instrument_type':inst['instrument_type']}
        return out

class _CsvSink:
    def write_options_data(self, *a, **k):
        # Use timezone-aware UTC now (utcnow deprecated)
        try:
            ts = dt.datetime.now(dt.UTC)
        except Exception:  # pragma: no cover - older Python fallback
            ts = dt.datetime.now(dt.timezone.utc)
        return {'expiry_code':'WEEKLY','pcr':1.0,'timestamp':ts,'day_width':1}
    def write_overview_snapshot(self, *a, **k):
        pass

_PARAMS = {"NIFTY": {"strikes_itm":1, "strikes_otm":1, "expiries":["this_week"]}}

def test_weekend_degraded_when_empty_data(monkeypatch):
    # Simulate weekend open override with zero field coverage leading to non-GREEN status
    monkeypatch.setenv('G6_WEEKEND_MODE','1')
    providers=_WeekendProviders()
    csv_sink=_CsvSink()
    metrics=types.SimpleNamespace(collection_cycle_in_progress=types.SimpleNamespace(set=lambda *_: None))
    res = run_unified_collectors(_PARAMS, providers, csv_sink, None, metrics, build_snapshots=True)
    indices = res.get('indices') or []
    assert indices, 'expected at least one index'
    status = (indices[0].get('status') or '').upper()
    # Expect either PARTIAL/EMPTY/STALE/DEGRADED but not OK/SYNTH due to zero field coverage
    assert status not in ('OK','SYNTH'), f'status should not be GREEN-equivalent; got {status}'
