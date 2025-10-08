import logging, datetime, pytest
from typing import Any
from src.collectors.modules import pipeline as pl
from src.collectors.pipeline.errors import PhaseRecoverableError

class Providers:
    def __init__(self, mode: str = 'ok'):
        self.mode = mode
    def get_atm_strike(self, index: str):
        return 1000
    def get_instrument_chain(self, index: str):
        if self.mode == 'fatal':
            raise RuntimeError('instrument boom')
        return ['A','B']

# Patch minimal functions to drive recoverable errors

def fake_build_expiry_map(instruments):
    return ({datetime.date.today(): instruments}, {'expiry_count': 1})

def fake_compute_strike_universe(atm, itm, otm, index_symbol):
    return [atm], {}

def fake_enrich_quotes(index_symbol, rule, expiry_date, exp_instruments, providers, metrics):
    return {s: {'bid':1,'ask':2} for s in exp_instruments}

def fake_run_preventive_validation(index_symbol, rule, expiry_date, exp_instruments, enriched, _):
    return enriched, {}

def fake_coverage_metrics(ctx, exp_instruments, strikes, index_symbol, rule, expiry_date):
    return {'strike_coverage': 1.0}

def fake_field_coverage_metrics(ctx, cleaned_enriched, index_symbol, rule, expiry_date):
    return {'field_coverage': 1.0}

def fake_finalize_expiry(expiry_rec, cleaned_enriched, strikes, index_symbol, expiry_date, rule, metrics):
    # Force recoverable error by raising PhaseRecoverableError to test classification
    raise PhaseRecoverableError('finalize_fail_injected')


def fake_adaptive_post_expiry(ctx, index_symbol, expiry_rec, rule):
    return None

@pytest.fixture(autouse=True)
def patch_pipeline(monkeypatch):
    monkeypatch.setattr(pl, 'build_expiry_map', fake_build_expiry_map, raising=True)
    monkeypatch.setattr(pl, 'compute_strike_universe', fake_compute_strike_universe, raising=True)
    monkeypatch.setattr(pl, 'enrich_quotes', fake_enrich_quotes, raising=True)
    monkeypatch.setattr(pl, 'run_preventive_validation', fake_run_preventive_validation, raising=False)
    monkeypatch.setattr(pl, 'coverage_metrics', fake_coverage_metrics, raising=True)
    monkeypatch.setattr(pl, 'field_coverage_metrics', fake_field_coverage_metrics, raising=True)
    monkeypatch.setattr(pl, '_finalize_expiry', fake_finalize_expiry, raising=False)
    monkeypatch.setattr(pl, 'adaptive_post_expiry', fake_adaptive_post_expiry, raising=True)
    yield


def test_recoverable_expiry_failure(caplog):
    caplog.set_level(logging.INFO, logger='src.collectors.pipeline')
    out = pl.run_pipeline({'X': {}}, Providers(mode='ok'), None, None, metrics=None, legacy_baseline={'indices': []})
    idx = out['indices'][0]
    assert idx['failures'] >= 1
    # Ensure failure logged as finalize_fail
    msgs = [r.message for r in caplog.records if r.name == 'src.collectors.pipeline']
    assert any('finalize_fail' in m for m in msgs)


def test_fatal_index_failure(caplog):
    caplog.set_level(logging.DEBUG, logger='src.collectors.pipeline')
    out = pl.run_pipeline({'Y': {}}, Providers(mode='fatal'), None, None, metrics=None, legacy_baseline={'indices': []})
    idx = out['indices'][0]
    assert idx['failures'] >= 1
    msgs = [r.message for r in caplog.records if r.name == 'src.collectors.pipeline']
    # Fatal path should log pipeline_index_failed
    assert any('pipeline_index_failed' in m for m in msgs)
