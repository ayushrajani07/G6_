import os, datetime as dt
from src.orchestrator.context import RuntimeContext
from src.orchestrator.cycle import run_cycle

class DummyMetrics:
    class DummyHist:
        def observe(self, *_):
            pass
    def __init__(self):
        self.cycle_time_seconds = self.DummyHist()
        self.cycle_sla_breach = type('X',(object,),{'inc':lambda self: None})()


def test_adaptive_strike_retry_increments(monkeypatch):
    monkeypatch.setenv('G6_FORCE_MARKET_OPEN','1')
    monkeypatch.setenv('G6_AUTO_SNAPSHOTS','0')  # not relevant
    # Low threshold forcing trigger (so even moderate coverage triggers)
    monkeypatch.setenv('G6_STRIKE_COVERAGE_OK','0.80')  # trigger becomes 0.72
    ctx = RuntimeContext(config={})
    ctx.index_params = {  # type: ignore[assignment]
        'NIFTY': {'strikes_itm': 2, 'strikes_otm': 2, 'expiries': ['this_week']}
    }
    # Provider producing coverage below trigger (simulate by only returning subset of strikes)
    class Prov:
        def get_index_data(self, index):
            return 20000.0, {'open':20000,'high':20000,'low':20000,'close':20000}
        def get_atm_strike(self, index):
            return 20000.0
        def resolve_expiry(self, index, rule):
            return dt.date.today()
        def get_expiry_dates(self, index):
            return [dt.date.today()]
        def get_option_instruments(self, index, expiry_date, strikes):
            # Return instruments for ONLY half the requested strikes to create low strike coverage
            half = strikes[: max(1, len(strikes)//2) ]
            out = []
            for s in half:
                for t in ('CE','PE'):
                    out.append({'tradingsymbol': f'{index}{int(s)}{t}', 'exchange':'NFO', 'instrument_type': t, 'strike': s, 'expiry': expiry_date})
            return out
        def enrich_with_quotes(self, instruments):
            q = {}
            for inst in instruments:
                sym = f"NFO:{inst['tradingsymbol']}"
                q[sym] = {'last_price':1.0,'volume':10,'oi':5,'avg_price':1.0,'strike':inst['strike'],'instrument_type':inst['instrument_type']}
            return q
    ctx.providers = Prov()
    class CsvSink:
        def write_options_data(self, *a, **k):
            # minimal payload
            return {'expiry_code': 'WEEKLY', 'pcr': 1.0, 'timestamp': dt.datetime.now(dt.timezone.utc), 'day_width': 1}
    ctx.csv_sink = CsvSink()
    ctx.influx_sink = None
    ctx.metrics = DummyMetrics()
    ctx.cycle_count = 0

    # Run one cycle -> should expand strikes_itm/otm due to low coverage
    run_cycle(ctx)
    new_cfg = ctx.index_params['NIFTY']  # type: ignore[index]
    assert new_cfg['strikes_itm'] >= 3 or new_cfg['strikes_otm'] >= 3, 'adaptive strike retry did not expand depth'

    # Second cycle shouldn't shrink values
    prev_itm = new_cfg['strikes_itm']; prev_otm = new_cfg['strikes_otm']
    run_cycle(ctx)
    assert ctx.index_params['NIFTY']['strikes_itm'] >= prev_itm
    assert ctx.index_params['NIFTY']['strikes_otm'] >= prev_otm
