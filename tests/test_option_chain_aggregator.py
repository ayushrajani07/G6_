from src.metrics import generated as m
from src.metrics.option_chain_aggregator import aggregate_once, _bucket_mny, _bucket_dte, MNY_BUCKETS, DTE_BUCKETS

def test_bucket_boundaries():
    # moneyness boundary checks
    assert _bucket_mny(-0.30) == 'deep_itm'
    assert _bucket_mny(-0.10) == 'itm'
    assert _bucket_mny(0.0) == 'atm'
    assert _bucket_mny(0.10) == 'otm'
    assert _bucket_mny(0.30) == 'deep_otm'
    # dte boundaries
    assert _bucket_dte(0.5) == 'ultra_short'
    assert _bucket_dte(2) == 'short'
    assert _bucket_dte(10) == 'medium'
    assert _bucket_dte(45) == 'long'
    assert _bucket_dte(120) == 'leap'


def test_aggregate_once_populates_metrics():
    # Invoke aggregation (uses synthetic data)
    aggregate_once()
    # We can't assert exact values (random), but ensure at least one sample labeled appears (ATM bucket typical)
    # Access underlying registry sample presence via generated accessor existence
    # Just ensure no exception and at least one label child creation path ran.
    # (Prometheus client doesn't expose simple read API without scraping; this is a smoke test.)
    # If needed we would integrate a custom registry; kept simple here.
    assert m.m_option_contracts_active_labels('atm','short') is not None  # type: ignore[attr-defined]
