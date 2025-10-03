import os
import datetime as dt
from types import SimpleNamespace

import pytest

from src.orchestrator.cycle import run_cycle
from src.orchestrator.context import RuntimeContext

# Auto-snapshot path now integrated into unified_collectors (build_snapshots flag)

class DummyMetrics:
    def __init__(self):
        class DummyHist:
            def observe(self, *_):
                pass
        self.cycle_time_seconds = DummyHist()
        def inc():
            pass
        self.cycle_sla_breach = SimpleNamespace(inc=inc)



@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in ["G6_AUTO_SNAPSHOTS", "G6_SNAPSHOT_CACHE", "G6_PARALLEL_INDICES"]:
        monkeypatch.delenv(var, raising=False)


def test_auto_snapshots_updates_cache(monkeypatch, tmp_path):
    # Enable snapshot cache & auto snapshots
    monkeypatch.setenv("G6_AUTO_SNAPSHOTS", "1")
    monkeypatch.setenv("G6_SNAPSHOT_CACHE", "1")

    # Prepare context
    ctx = RuntimeContext(config={})
    ctx.index_params = {"NIFTY": {"strikes_itm": 2, "strikes_otm": 2}}  # type: ignore[assignment]
    # Minimal provider facade with required methods for unified collectors (index data + atm + expiry + instruments + quotes)
    class DummyProviders:
        def get_index_data(self, index):
            return 20000.0, {'open':20000,'high':20010,'low':19990,'close':20000}
        def get_atm_strike(self, index):
            return 20000.0
        def resolve_expiry(self, index, rule):  # simple: treat rule as ISO date today
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
    ctx.providers = DummyProviders()
    class DummyCsvSink:
        def write_options_data(self, index_symbol, expiry_date, enriched_data, collection_time, **kw):
            # return metrics payload expected keys
            return {'expiry_code': 'WEEKLY', 'pcr': 1.0, 'timestamp': collection_time, 'day_width': 1}
        def write_overview_snapshot(self, *a, **k):
            pass
    ctx.csv_sink = DummyCsvSink()
    ctx.influx_sink = None
    ctx.metrics = DummyMetrics()
    ctx.cycle_count = 0

    # Snapshots cache module
    from src.domain import snapshots_cache
    snapshots_cache._SNAPSHOTS.clear()

    # Build synthetic snapshots objects matching expected interface
    from src.domain.models import ExpirySnapshot, OptionQuote
    synthetic_snapshot = ExpirySnapshot(
        index="NIFTY",
        expiry_rule="WEEKLY",
        expiry_date=dt.date.today(),
        atm_strike=20000,
        options=[OptionQuote(symbol="NIFTY24SEP20000CE", exchange="NSE", last_price=1.0)],
        generated_at=dt.datetime.now(dt.timezone.utc),
    )

    # Monkeypatch unified_collectors.run_unified_collectors to inject snapshot list
    import src.collectors.unified_collectors as uni_mod  # type: ignore
    real_run = uni_mod.run_unified_collectors
    def fake_run_unified_collectors(*a, **kw):
        res = real_run(*a, **kw)
        if isinstance(res, dict) and kw.get('build_snapshots'):
            res['snapshots'] = [synthetic_snapshot]
            res['snapshot_count'] = 1
        return res
    uni_mod.run_unified_collectors = fake_run_unified_collectors  # type: ignore

    elapsed = run_cycle(ctx)
    assert elapsed >= 0.0
    # Ensure cache updated
    ser = snapshots_cache.serialize()
    assert isinstance(ser, dict)
    # After cycle snapshots should be present (injected via monkeypatch)
    assert ser.get('count') == 1
    snaps = ser.get('snapshots')  # type: ignore[assignment]
    assert isinstance(snaps, list)
    assert snaps and snaps[0]['index'] == 'NIFTY'  # type: ignore[index]
    # Overview present with at least one index
    ov = ser.get('overview')  # type: ignore[assignment]
    assert ov is not None
    assert ov['total_indices'] >= 1  # type: ignore[index]

