import datetime
from types import SimpleNamespace

import pytest

from src.collectors.modules.synthetic_fallback import ensure_synthetic_quotes


class TraceRecorder:
    def __init__(self):
        self.events = []
    def __call__(self, event, **fields):  # mimic _trace signature
        self.events.append((event, fields))


def _gen_synth(instruments):
    # Deterministic synthetic: one record per instrument id/strike
    out = {}
    for inst in instruments:
        sym = inst.get('symbol') or f"SYN-{inst.get('strike')}"
        out[sym] = {'strike': inst.get('strike'), 'instrument_type': inst.get('type','CE'), 'synthetic': True}
    return out


def test_no_fallback_when_enriched_present():
    trace = TraceRecorder()
    expiry_rec = {}
    enriched = {'OPT100CE': {'strike': 100}}
    insts = [{'strike': 100, 'symbol': 'OPT100CE'}]
    def handle_error(e):
        raise AssertionError("handle_error should not be called when enriched present")
    new_enriched, early = ensure_synthetic_quotes(
        enriched,
        insts,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        expiry_date=datetime.date(2025,1,30),
        trace=trace,
        generate_synthetic_quotes=_gen_synth,
        expiry_rec=expiry_rec,
        handle_error=handle_error,
    )
    assert new_enriched is enriched
    assert early is False
    assert 'synthetic_fallback' not in expiry_rec
    assert not trace.events


def test_synthetic_fallback_success():
    trace = TraceRecorder()
    expiry_rec = {}
    enriched = {}  # empty triggers fallback
    insts = [{'strike': 101, 'symbol': 'OPT101PE', 'type': 'PE'}]
    def handle_error(e):
        raise AssertionError("error handler should not run on successful synthetic generation")
    new_enriched, early = ensure_synthetic_quotes(
        enriched,
        insts,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        expiry_date=datetime.date(2025,1,30),
        trace=trace,
        generate_synthetic_quotes=_gen_synth,
        expiry_rec=expiry_rec,
        handle_error=handle_error,
    )
    assert new_enriched
    assert early is False
    assert expiry_rec.get('synthetic_fallback') is True
    assert any(ev[0]=='synthetic_quotes_fallback' for ev in trace.events)


def test_synthetic_fallback_failure():
    trace = TraceRecorder()
    expiry_rec = {}
    enriched = {}  # empty triggers fallback
    insts = [{'strike': 102, 'symbol': 'OPT102CE'}]
    def gen_empty(_):
        return {}  # force failure path
    called = {'err': False}
    def handle_error(e):
        called['err'] = True
    new_enriched, early = ensure_synthetic_quotes(
        enriched,
        insts,
        index_symbol='NIFTY',
        expiry_rule='2025-01-30',
        expiry_date=datetime.date(2025,1,30),
        trace=trace,
        generate_synthetic_quotes=gen_empty,
        expiry_rec=expiry_rec,
        handle_error=handle_error,
    )
    assert new_enriched == {}
    assert early is True
    assert called['err'] is True
    assert 'synthetic_fallback' not in expiry_rec  # not set on failure
    # No synthetic fallback trace event since generation failed
    assert not any(ev[0]=='synthetic_quotes_fallback' for ev in trace.events)
