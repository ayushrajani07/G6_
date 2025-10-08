from __future__ import annotations

"""Tests mapping provider domain exceptions to taxonomy recoverable outcomes.

Covers:
  - phase_fetch: NoInstrumentsError -> PhaseRecoverableError classification.
  - phase_enrich: NoQuotesError -> PhaseRecoverableError classification.
"""

from src.collectors.pipeline.state import ExpiryState
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.phases import phase_fetch, phase_enrich
from src.utils.exceptions import NoInstrumentsError, NoQuotesError


class ProvidersNoInstruments:
    def get_option_instruments(self, index, expiry_date, strikes):  # noqa: D401
        raise NoInstrumentsError("no instruments test")


class ProvidersNoQuotes:
    def get_option_instruments(self, index, expiry_date, strikes):  # minimal instrument set
        return [{"symbol": "OPT1", "strike": strikes[0], "expiry": expiry_date, "instrument_type": "CE"}]

    def enrich_with_quotes(self, instruments):  # noqa: D401
        raise NoQuotesError("no quotes test")


class CtxFetch:
    def __init__(self):
        self.providers = ProvidersNoInstruments()


class CtxEnrich:
    def __init__(self):
        self.providers = ProvidersNoQuotes()


def test_phase_fetch_domain_no_instruments_recoverable():
    ctx = CtxFetch()
    st = ExpiryState(index="NIFTY", rule="weekly", settings=object())
    st.expiry_date = __import__('datetime').date.today()
    phases = [lambda c, s: phase_fetch(c, s, precomputed_strikes=[100, 101])]
    out = execute_phases(ctx, st, phases)
    # Expect recoverable classification from executor (recoverable:phase_fetch)
    assert any(e.startswith('fetch_recoverable:') or e.startswith('recoverable:phase_fetch:') for e in out.errors), out.errors


def test_phase_enrich_domain_no_quotes_recoverable():
    ctx = CtxEnrich()
    st = ExpiryState(index="NIFTY", rule="weekly", settings=object())
    st.expiry_date = __import__('datetime').date.today()
    # Seed instruments so enrich is attempted
    st.instruments = [{"symbol": "OPT1", "strike": 100, "expiry": st.expiry_date, "instrument_type": "CE"}]
    phases = [phase_enrich]
    out = execute_phases(ctx, st, phases)
    assert any(e.startswith('enrich_recoverable:') or e.startswith('recoverable:phase_enrich:') for e in out.errors), out.errors
