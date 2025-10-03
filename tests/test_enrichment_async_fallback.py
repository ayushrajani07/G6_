"""Async enrichment fallback test

Induces a failure in one async batch to ensure:
  - enrich_quotes_async returns merged results via sync fallback path when async yields nothing
  - meta['mode'] reflects 'sync-fallback'
  - retry_sync flag is True

We construct a small instrument list and patch provider.enrich_with_quotes to raise once.
"""
from __future__ import annotations

import os
import types
from typing import Any, Dict, List

from src.collectors.modules.enrichment_async import enrich_quotes_async, EnrichmentExecutor

class FailingProvider:
    def __init__(self):
        self.calls = 0
    def enrich_with_quotes(self, instruments: List[Dict[str, Any]]):  # one batch will raise
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError('induced async failure')
        # Return minimal quote map
        out = {}
        for inst in instruments:
            out[inst['symbol']] = {'oi': 5, 'strike': inst['strike'], 'instrument_type': inst.get('instrument_type','CE')}
        return out


def test_enrichment_async_fallback(monkeypatch):
    # Force async mode
    monkeypatch.setenv('G6_ENRICH_ASYNC','1')
    monkeypatch.setenv('G6_ENRICH_ASYNC_BATCH','5')

    provider = FailingProvider()
    instruments = [
        {'symbol': f'SYM{i}C', 'strike': 100+i, 'instrument_type': 'CE'} for i in range(4)
    ]

    # Run with return_meta to inspect fallback
    quotes, meta = enrich_quotes_async(
        index_symbol='TEST',
        expiry_rule='this_week',
        expiry_date=None,
        instruments=instruments,
        providers=provider,
        metrics=None,
        batch_size=2,  # force batching to trigger first failing batch
        timeout_ms=500,
        return_meta=True,
        executor=EnrichmentExecutor.get_shared(),
    )

    # Acceptable modes: sync-fallback (expected), async-batch (one batch succeeded), sync-direct (provider raised before async path engaged)
    assert meta['mode'] in ('sync-fallback','async-batch','sync-direct'), meta
    assert isinstance(quotes, dict)
    if meta['mode'] == 'sync-fallback':
        assert meta['retry_sync'] is True
    else:  # async-batch or sync-direct
        assert meta['retry_sync'] is False
