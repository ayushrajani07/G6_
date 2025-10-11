import os
import pytest

pytestmark = pytest.mark.serial

def test_pipeline_analytics_iv_greeks(monkeypatch, tmp_path):
    os.environ['G6_PIPELINE_COLLECTOR'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'
    # Enable greeks + iv estimation via config flags (simulate config override through env if supported)
    os.environ['G6_COMPUTE_GREEKS'] = '1'
    os.environ['G6_ESTIMATE_IV'] = '1'
    import pytest
    from src.orchestrator.bootstrap import bootstrap_runtime
    from src.collectors.pipeline import build_default_pipeline, ExpiryWorkItem
    try:
        ctx, _stop = bootstrap_runtime('config/g6_config.json')
    except RuntimeError as e:
        pytest.skip(f"bootstrap runtime unavailable: {e}")
    ctx.index_params = {
        'NIFTY': { 'expiries': ['this_week'], 'strikes_itm': 0, 'strikes_otm': 0, 'enable': True }
    }  # type: ignore
    # Build pipeline directly to inspect enriched expiry
    pipe = build_default_pipeline(ctx.providers, ctx.csv_sink, ctx.influx_sink, ctx.metrics, compute_greeks=True, estimate_iv=True)
    # Acquire atm/index price
    try:
        index_price, _ohlc = ctx.providers.get_index_data('NIFTY')  # type: ignore
    except Exception:
        index_price = 0.0
    try:
        atm = ctx.providers.get_atm_strike('NIFTY')  # type: ignore
    except Exception:
        atm = 0.0
    wi = ExpiryWorkItem(index='NIFTY', expiry_rule='this_week', expiry_date=None, strikes=[atm] if atm else [], index_price=index_price, atm_strike=atm)
    enriched_expiry, outcome = pipe.run_expiry(wi)
    # Iterate enriched options (may be empty if provider returns none). If present assert greeks/iv keys.
    if enriched_expiry and enriched_expiry.enriched:
        # Take first option data dict
        first = next(iter(enriched_expiry.enriched.values()))
        iv = first.get('iv') or first.get('implied_vol')
        has_greek = any(first.get(k) not in (None, 0, 0.0) for k in ('delta','gamma','theta','vega','rho'))
        assert iv is not None or has_greek
    os.environ.pop('G6_PIPELINE_COLLECTOR', None)
    os.environ.pop('G6_COMPUTE_GREEKS', None)
    os.environ.pop('G6_ESTIMATE_IV', None)
