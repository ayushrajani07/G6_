import os
import types
from src.collectors.modules.enrichment_async import enrich_quotes_async, get_enrichment_mode

class DummyProviders:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
    def enrich_with_quotes(self, instruments):
        self.calls.append(list(instruments))
        if self.fail:
            raise RuntimeError('boom')
        # Return mapping keyed by tradingsymbol or synthesized symbol
        out = {}
        for inst in instruments:
            sym = inst.get('tradingsymbol') or inst.get('symbol') or f"S{len(out)}"
            out[sym] = {**inst, 'last_price': 1.0, 'volume': 10, 'oi': 5}
        return out


def _set_flag(on: bool):
    if on:
        os.environ['G6_ENRICH_ASYNC'] = '1'
    else:
        os.environ.pop('G6_ENRICH_ASYNC', None)


def test_async_disabled_delegates_sync(monkeypatch):
    _set_flag(False)
    # Monkeypatch sync enrich to observe call
    from src.collectors.modules import enrichment as sync_mod
    called = {}
    def fake_sync(index_symbol, rule, expiry_date, instruments, providers, metrics):
        called['args'] = (index_symbol, rule, len(instruments))
        return {'X': {'last_price': 1}}
    monkeypatch.setattr(sync_mod, 'enrich_quotes', fake_sync)
    prov = DummyProviders()
    result = enrich_quotes_async('NIFTY', 'this_week', None, [{'tradingsymbol':'AA'}], prov, metrics=None)
    assert 'X' in result
    assert get_enrichment_mode().startswith('sync')
    assert called


def test_async_single_bulk(monkeypatch):
    _set_flag(True)
    os.environ.pop('G6_ENRICH_ASYNC_BATCH', None)
    prov = DummyProviders()
    # Monkeypatch sync enrich called inside async path
    from src.collectors.modules import enrichment as sync_mod
    def fake_sync(index_symbol, rule, expiry_date, instruments, providers, metrics):
        return {inst['tradingsymbol']: {'last_price': 2} for inst in instruments}
    monkeypatch.setattr(sync_mod, 'enrich_quotes', fake_sync)
    instruments = [{'tradingsymbol': f'SYM{i}'} for i in range(5)]
    out = enrich_quotes_async('NIFTY', 'this_week', None, instruments, prov, metrics=None)
    assert len(out) == 5
    # Should have only one provider call (bulk) or match sync fallback semantics


def test_async_batched_success(monkeypatch):
    _set_flag(True)
    os.environ['G6_ENRICH_ASYNC_BATCH'] = '2'
    prov = DummyProviders()
    from src.collectors.modules import enrichment as sync_mod
    def fake_sync(index_symbol, rule, expiry_date, instruments, providers, metrics):
        return {inst['tradingsymbol']: {'last_price': 3} for inst in instruments}
    monkeypatch.setattr(sync_mod, 'enrich_quotes', fake_sync)
    instruments = [{'tradingsymbol': f'SYM{i}'} for i in range(5)]
    out = enrich_quotes_async('NIFTY', 'this_week', None, instruments, prov, metrics=None)
    assert len(out) == 5
    # Ensure provider saw multiple batches
    assert len(prov.calls) >= 2


def test_async_failure_fallback_sync(monkeypatch):
    _set_flag(True)
    os.environ['G6_ENRICH_ASYNC_BATCH'] = '2'
    prov = DummyProviders(fail=True)
    from src.collectors.modules import enrichment as sync_mod
    def fake_sync(index_symbol, rule, expiry_date, instruments, providers, metrics):
        return {inst['tradingsymbol']: {'last_price': 5} for inst in instruments}
    monkeypatch.setattr(sync_mod, 'enrich_quotes', fake_sync)
    instruments = [{'tradingsymbol': f'SYM{i}'} for i in range(3)]
    out = enrich_quotes_async('NIFTY', 'this_week', None, instruments, prov, metrics=None)
    assert len(out) == 3
    # Async failed so provider fail means no calls recorded? Actually it raises after each, still counts
    assert prov.calls  # calls attempted


def test_async_empty_retry_sync(monkeypatch):
    _set_flag(True)
    os.environ.pop('G6_ENRICH_ASYNC_BATCH', None)
    prov = DummyProviders()
    from src.collectors.modules import enrichment as sync_mod
    def fake_sync(index_symbol, rule, expiry_date, instruments, providers, metrics):
        # Force empty to trigger synthetic fallback path later
        return {}
    monkeypatch.setattr(sync_mod, 'enrich_quotes', fake_sync)
    instruments = [{'tradingsymbol': 'ONLY'}]
    out = enrich_quotes_async('NIFTY', 'this_week', None, instruments, prov, metrics=None)
    # Out may still be empty (since sync fallback also empty) but no exception
    assert isinstance(out, dict)
