import os
import importlib
import datetime as dt

from src.collectors.modules.prefilter_flow import run_prefilter_clamp


def _build_instruments(n):
    return [{'strike': i, 'symbol': f'SYM{i}'} for i in range(n)]


def test_prefilter_disabled(monkeypatch):
    monkeypatch.setenv('G6_PREFILTER_DISABLE', '1')
    insts = _build_instruments(10)
    new_list, meta = run_prefilter_clamp('NIFTY', 'this_week', dt.date(2025,1,30), insts)
    assert len(new_list) == 10
    assert meta is None


def test_prefilter_clamps(monkeypatch):
    """Clamp applies only when original_count > max_allowed and max_allowed >= floor (50)."""
    monkeypatch.delenv('G6_PREFILTER_DISABLE', raising=False)
    monkeypatch.setenv('G6_PREFILTER_MAX_INSTRUMENTS', '60')
    insts = _build_instruments(120)
    new_list, meta = run_prefilter_clamp('NIFTY', 'this_week', dt.date(2025,1,30), insts)
    assert len(new_list) == 60
    assert meta is not None
    orig, dropped, max_allowed, strict = meta
    assert orig == 120 and dropped == 60 and max_allowed == 60


def test_prefilter_no_clamp_needed(monkeypatch):
    monkeypatch.delenv('G6_PREFILTER_DISABLE', raising=False)
    monkeypatch.setenv('G6_PREFILTER_MAX_INSTRUMENTS', '50')
    insts = _build_instruments(20)
    new_list, meta = run_prefilter_clamp('NIFTY', 'this_week', dt.date(2025,1,30), insts)
    assert len(new_list) == 20
    assert meta is None


def test_prefilter_floor_prevents_small_max(monkeypatch):
    """Setting env below floor should yield no clamp when count < 50."""
    monkeypatch.delenv('G6_PREFILTER_DISABLE', raising=False)
    monkeypatch.setenv('G6_PREFILTER_MAX_INSTRUMENTS', '5')  # below floor -> treated as 50
    insts = _build_instruments(30)
    new_list, meta = run_prefilter_clamp('NIFTY', 'this_week', dt.date(2025,1,30), insts)
    assert len(new_list) == 30  # unchanged
    assert meta is None
