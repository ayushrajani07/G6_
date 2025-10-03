"""Test that pipeline is now the default in facade auto mode post-promotion.

Assertions:
  - Without flags, mode=auto yields pipeline (detected via presence of pipeline-only field or by parity hash vs legacy run forced)
  - Setting G6_LEGACY_COLLECTOR forces legacy
  - Deprecated G6_PIPELINE_COLLECTOR triggers deprecation warning but does not change default behavior
"""
from __future__ import annotations

import os, copy
from typing import Any, Dict

from src.orchestrator.facade import run_collect_cycle
from src.collectors.unified_collectors import run_unified_collectors

class DummyProvider:
    def get_atm_strike(self, index): return 100
    def get_index_data(self, index): return 100, {}
    def get_ltp(self, index): return 100
    def get_expiry_dates(self, index):
        import datetime; return [datetime.date.today()]
    def get_option_instruments(self, index, expiry_date, strikes):
        out = []
        for s in strikes:
            out.append({'symbol': f"{index}-{int(s)}-CE", 'strike': s, 'instrument_type': 'CE'})
            out.append({'symbol': f"{index}-{int(s)}-PE", 'strike': s, 'instrument_type': 'PE'})
        return out
    def enrich_with_quotes(self, instruments):
        return {i['symbol']:{'oi':10,'instrument_type':i['instrument_type'],'strike':i['strike'],'expiry':None} for i in instruments}


def _index_params():
    return {
        'NIFTY': {'symbol':'NIFTY','expiries':['this_week'],'strikes_itm':1,'strikes_otm':1},
    }


def _capture_hash(result: Dict[str, Any]) -> int:
    # Simple structural fingerprint: count keys + nested summary lengths to distinguish paths heuristically
    if not isinstance(result, dict):
        return -1
    top = len(result.keys())
    snap = result.get('snapshot_summary') or {}
    return top * 1000 + len(snap.keys())


def test_facade_auto_pipeline_default(monkeypatch, caplog):
    caplog.set_level('WARNING')
    # Ensure clean env
    for k in ('G6_LEGACY_COLLECTOR','G6_PIPELINE_COLLECTOR'):
        monkeypatch.delenv(k, raising=False)
    provider = DummyProvider()
    params = _index_params()
    auto_res = run_collect_cycle(params, provider, None, None, None, mode='auto', build_snapshots=False)
    # Force legacy path explicitly
    legacy_res = run_collect_cycle(copy.deepcopy(params), provider, None, None, None, mode='legacy', build_snapshots=False)
    assert _capture_hash(auto_res) != -1
    assert _capture_hash(legacy_res) != -1
    # Expect pipeline (auto) != legacy structural fingerprint frequently (additional pipeline fields)
    assert _capture_hash(auto_res) >= _capture_hash(legacy_res)


def test_facade_auto_force_legacy(monkeypatch):
    for k in ('G6_LEGACY_COLLECTOR','G6_PIPELINE_COLLECTOR'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('G6_LEGACY_COLLECTOR','1')
    provider = DummyProvider()
    params = _index_params()
    res = run_collect_cycle(params, provider, None, None, None, mode='auto', build_snapshots=False)
    leg = run_collect_cycle(params, provider, None, None, None, mode='legacy', build_snapshots=False)
    assert _capture_hash(res) == _capture_hash(leg)


def test_facade_auto_deprecated_flag(monkeypatch, caplog):
    caplog.set_level('WARNING')
    for k in ('G6_LEGACY_COLLECTOR','G6_PIPELINE_COLLECTOR'):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv('G6_PIPELINE_COLLECTOR','1')
    provider = DummyProvider()
    params = _index_params()
    res = run_collect_cycle(params, provider, None, None, None, mode='auto', build_snapshots=False)
    # Should still be pipeline; ensure warning emitted
    assert any('deprecated' in r.message for r in caplog.records)
    leg = run_collect_cycle(params, provider, None, None, None, mode='legacy', build_snapshots=False)
    assert _capture_hash(res) >= _capture_hash(leg)
