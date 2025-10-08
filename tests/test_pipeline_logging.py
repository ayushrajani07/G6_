import os, logging, importlib
from typing import Any, Dict
import datetime
import pytest

# We target the pipeline module directly for controlled dependency patching
from src.collectors.modules import pipeline as pl

class FakeProviders:
    def get_atm_strike(self, index: str):
        return 500
    def get_instrument_chain(self, index: str):
        # Minimal instrument list (structure opaque to our patched functions)
        return ['OPT1', 'OPT2', 'OPT3']

# --- Patched dependency implementations ---

def fake_build_expiry_map(instruments):
    return ({datetime.date.today(): instruments}, {'expiry_count': 1})

def fake_compute_strike_universe(atm, itm, otm, index_symbol):
    strikes = [atm - 100, atm, atm + 100]
    return strikes, {'atm': atm, 'itm': itm, 'otm': otm}

def fake_enrich_quotes(index_symbol, rule, expiry_date, exp_instruments, providers, metrics):
    return {sym: {'bid': 1, 'ask': 2} for sym in exp_instruments}

def fake_run_preventive_validation(index_symbol, rule, expiry_date, exp_instruments, enriched, _):
    return enriched, {'validated': True}

def fake_coverage_metrics(ctx, exp_instruments, strikes, index_symbol, rule, expiry_date):
    return {'strike_coverage': 0.75}

def fake_field_coverage_metrics(ctx, cleaned_enriched, index_symbol, rule, expiry_date):
    return {'field_coverage': 0.60}

def fake_compute_expiry_status(expiry_rec):
    # Mark PARTIAL if field coverage missing
    if expiry_rec.get('field_coverage') is None:
        return 'PARTIAL'
    return expiry_rec['status']

def fake_finalize_expiry(expiry_rec, cleaned_enriched, strikes, index_symbol, expiry_date, rule, metrics):
    # No-op finalize
    return None

def fake_adaptive_post_expiry(ctx, index_symbol, expiry_rec, rule):
    return None

@pytest.fixture(autouse=True)
def patch_pipeline(monkeypatch):
    # Patch imported symbols inside pipeline module
    monkeypatch.setattr(pl, 'build_expiry_map', fake_build_expiry_map, raising=True)
    monkeypatch.setattr(pl, 'compute_strike_universe', fake_compute_strike_universe, raising=True)
    monkeypatch.setattr(pl, 'enrich_quotes', fake_enrich_quotes, raising=True)
    monkeypatch.setattr(pl, 'run_preventive_validation', fake_run_preventive_validation, raising=False)
    monkeypatch.setattr(pl, 'coverage_metrics', fake_coverage_metrics, raising=True)
    monkeypatch.setattr(pl, 'field_coverage_metrics', fake_field_coverage_metrics, raising=True)
    monkeypatch.setattr(pl, '_compute_expiry_status', fake_compute_expiry_status, raising=False)
    monkeypatch.setattr(pl, '_finalize_expiry', fake_finalize_expiry, raising=False)
    monkeypatch.setattr(pl, 'adaptive_post_expiry', fake_adaptive_post_expiry, raising=True)
    yield

@pytest.fixture
def fake_index_params():
    return {'DEMO': {'strikes_itm': 1, 'strikes_otm': 1}}

# --- Tests ---

def test_pipeline_phase_logging_success(caplog, fake_index_params):
    providers = FakeProviders()
    caplog.set_level(logging.INFO, logger='src.collectors.pipeline')
    out = pl.run_pipeline(fake_index_params, providers, None, None, metrics=None, legacy_baseline={'indices': [{'index': 'BASE', 'status': 'OK'}]})
    # Basic assertions on output structure
    assert out.get('status') == 'ok'
    assert len(out.get('indices', [])) == 1
    # Ensure some phase logs present
    messages = [r.message for r in caplog.records if r.name == 'src.collectors.pipeline']
    assert any('phase=atm' in m for m in messages)
    assert any('phase=expiry_map' in m for m in messages)
    assert any('phase=strike_universe' in m for m in messages)
    assert any('phase=enrich' in m for m in messages)
    assert any('phase=coverage' in m for m in messages)


def test_pipeline_parity_score_log(caplog, fake_index_params, monkeypatch):
    providers = FakeProviders()
    caplog.set_level(logging.INFO, logger='src.collectors.pipeline')
    monkeypatch.setenv('G6_PIPELINE_PARITY_LOG', '1')
    _ = pl.run_pipeline(fake_index_params, providers, None, None, metrics=None, legacy_baseline={'indices': [{'index': 'BASE', 'status': 'OK', 'option_count': 3}]})
    parity_records = [r for r in caplog.records if r.name == 'src.collectors.pipeline' and r.getMessage() == 'pipeline_parity_score']
    assert parity_records, 'Expected pipeline_parity_score log record'
    # Check extra fields
    assert hasattr(parity_records[0], 'score')


def test_pipeline_taxonomy_fatal(monkeypatch, caplog, fake_index_params):
    class FailingProviders(FakeProviders):
        def get_instrument_chain(self, index: str):
            raise RuntimeError('boom')
    caplog.set_level(logging.DEBUG, logger='src.collectors.pipeline')
    monkeypatch.setenv('G6_PIPELINE_PARITY_LOG', '0')
    out = pl.run_pipeline(fake_index_params, FailingProviders(), None, None, metrics=None, legacy_baseline=None)
    indices = out.get('indices', [])
    assert indices, 'indices should be present'
    idx = indices[0]
    assert idx.get('failures', 0) >= 1
    # Ensure failure log present
    debug_msgs = [r.message for r in caplog.records if r.name == 'src.collectors.pipeline']
    assert any('pipeline_index_failed' in m or 'instrument_fetch_failed' in m for m in debug_msgs)
