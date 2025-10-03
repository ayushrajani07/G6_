import os
from src.metrics import get_metrics  # facade import
from src.collectors.unified_collectors import _iv_estimation_block

class DummyGreeksCalc:
    def implied_volatility(self, is_call, S, K, T, market_price, r, max_iterations, precision, min_iv, max_iv, return_iterations=True):
        # Return a fixed IV and synthetic iteration count derived from strike distance
        iters = int(abs(K - S)/ (S*0.01)) + 2  # ensure >0
        return 0.5, iters

def test_iv_iterations_histogram_observes(monkeypatch):
    os.environ['G6_ESTIMATE_IV'] = '1'
    # Minimal ctx with metrics
    metrics = get_metrics()
    class Ctx: pass
    ctx = Ctx()
    ctx.metrics = metrics

    # Enriched data: fabricate 3 options with varying strikes
    enriched = {
        'OPT1': {'strike': 100, 'last_price': 10},
        'OPT2': {'strike': 103, 'last_price': 11},
        'OPT3': {'strike': 110, 'last_price': 12},
    }
    index_symbol = 'NIFTY'
    expiry_rule = 'weekly'
    expiry_date = 0.05  # time fraction placeholder accepted by calculator
    index_price = 100

    _iv_estimation_block(ctx, enriched, index_symbol, expiry_rule, expiry_date, index_price, DummyGreeksCalc(), True, 0.05, 20, 0.01, 3.0, 1e-5)

    # Histogram internal state holds sum/count buckets; we just assert attribute exists and at least one bucket sample recorded via _sum
    hist = getattr(metrics, 'iv_iterations_histogram', None)
    assert hist is not None, 'Histogram metric missing'
    # Access underlying samples via private registry exposition (Prometheus client stores in _metrics)
    # We fetch the child by labels
    child = hist.labels(index=index_symbol, expiry=expiry_rule)
    # Prometheus client stores MutexValue; use get() to read numeric
    sample = getattr(child, '_sum', None)
    val = None
    try:
        if sample is not None:
            val = sample.get()  # type: ignore[attr-defined]
    except Exception:
        pass
    assert isinstance(val, (int,float)) and val > 0, 'Expected positive iteration sum after observations'
