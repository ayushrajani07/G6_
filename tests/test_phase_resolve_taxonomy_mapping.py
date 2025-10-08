from __future__ import annotations

"""Verify provider ResolveExpiryError maps to taxonomy abort via phase_resolve."""

import types
from src.collectors.pipeline.state import ExpiryState
from src.collectors.pipeline.executor import execute_phases
from src.collectors.pipeline.phases import phase_resolve
from src.utils.exceptions import ResolveExpiryError


class ProvidersStub:
    def get_expiry_dates(self, index_symbol):  # noqa: D401
        raise ResolveExpiryError(f"No future expiries for {index_symbol}")


class Ctx:
    def __init__(self):
        self.providers = ProvidersStub()


def test_phase_resolve_maps_resolve_expiry_error_to_abort():
    ctx = Ctx()
    st = ExpiryState(index="NIFTY", rule="this_week", settings=object())
    out = execute_phases(ctx, st, [phase_resolve])
    # Expect an abort classification in errors (resolve_abort prefix) and no expiry_date
    assert out.expiry_date is None
    assert any(e.startswith("resolve_abort:") for e in out.errors), out.errors
    # Executor should record abort classification (error list contains phase_resolve taxonomy line)
    # Ensure no generic fatal recorded
    assert not any(e.startswith("fatal:") for e in out.errors)
