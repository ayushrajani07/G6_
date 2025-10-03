import os
from src.utils.index_registry import get_index_meta, IndexMeta


def test_registry_core_indices():
    nifty = get_index_meta("nifty")  # case insensitivity
    bank = get_index_meta("BANKNIFTY")
    assert isinstance(nifty, IndexMeta)
    assert nifty.symbol == "NIFTY" and nifty.step == 50.0 and nifty.synthetic_atm > 20000
    assert bank.symbol == "BANKNIFTY" and bank.step == 100.0 and bank.synthetic_atm > 30000


def test_registry_env_override(monkeypatch):
    monkeypatch.setenv("G6_STRIKE_STEP_NIFTY", "75")
    meta = get_index_meta("NIFTY")
    assert meta.step == 75.0  # override applied
    # Ensure other fields unchanged
    base = get_index_meta("NIFTY")  # fetch again (idempotent with override)
    assert base.synthetic_atm == meta.synthetic_atm


def test_registry_unknown_defaults():
    x = get_index_meta("FOOIDX")
    assert x.symbol == "FOOIDX"
    assert x.step == 50.0  # generic fallback
    assert x.synthetic_atm == 20000  # fallback synth
