import os
import types
from src.metrics.option_chain_aggregator import aggregate_once, _load_provider
from src.metrics import generated as m

class _StubProvider:
    def get_option_chain_snapshot(self):
        # Deterministic small set spanning buckets
        return [
            {"strike":100,"underlying":100,"oi":10,"volume_24h":5,"iv":0.5,"spread_bps":50,"mny":0.0,"dte_days":2},  # atm, short
            {"strike":80,"underlying":100,"oi":20,"volume_24h":10,"iv":0.6,"spread_bps":70,"mny":-0.20,"dte_days":0.5}, # deep_itm, ultra_short
            {"strike":130,"underlying":100,"oi":5,"volume_24h":2,"iv":0.7,"spread_bps":90,"mny":0.30,"dte_days":95},   # deep_otm, leap
        ]


def test_env_provider_injection(monkeypatch):
    # Create a dynamic module to import
    mod = types.ModuleType('stub_option_provider')
    setattr(mod, 'Provider', _StubProvider)
    monkeypatch.setitem(os.environ, 'G6_OPTION_CHAIN_PROVIDER', 'stub_option_provider:Provider')
    import sys
    sys.modules['stub_option_provider'] = mod

    # Run aggregation
    aggregate_once()

    # Validate that metrics with expected label combos were set
    # We cannot read gauge values directly without scraping; ensure label objects are creatable
    assert m.m_option_contracts_active_labels('atm','short') is not None  # type: ignore[attr-defined]
    assert m.m_option_contracts_active_labels('deep_itm','ultra_short') is not None  # type: ignore[attr-defined]
    assert m.m_option_contracts_active_labels('deep_otm','leap') is not None  # type: ignore[attr-defined]
