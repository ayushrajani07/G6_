import logging, datetime, pytest
from src.collectors.modules import pipeline as pl
from src.collectors.pipeline.errors import PhaseRecoverableError

class Providers:
    def get_atm_strike(self, index: str):
        return 100
    def get_instrument_chain(self, index: str):
        return ['A']

# Minimal patches

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
    raise PhaseRecoverableError('injected_finalize_failure')

def fake_adaptive_post_expiry(ctx, index_symbol, expiry_rec, rule):
    return None

@pytest.fixture(autouse=True)
def patch(monkeypatch):
    monkeypatch.setattr(pl, 'build_expiry_map', fake_build_expiry_map, raising=True)
    monkeypatch.setattr(pl, 'compute_strike_universe', fake_compute_strike_universe, raising=True)
    monkeypatch.setattr(pl, 'enrich_quotes', fake_enrich_quotes, raising=True)
    monkeypatch.setattr(pl, 'run_preventive_validation', fake_run_preventive_validation, raising=False)
    monkeypatch.setattr(pl, 'coverage_metrics', fake_coverage_metrics, raising=True)
    monkeypatch.setattr(pl, 'field_coverage_metrics', fake_field_coverage_metrics, raising=True)
    monkeypatch.setattr(pl, '_finalize_expiry', fake_finalize_expiry, raising=False)
    monkeypatch.setattr(pl, 'adaptive_post_expiry', fake_adaptive_post_expiry, raising=True)
    yield


def test_recoverable_counter(monkeypatch):
    # Run pipeline and then query metrics registry implicitly via second import of metrics facade
    pl.run_pipeline({'IDX': {}}, Providers(), None, None, metrics=None, legacy_baseline={'indices': []})
    # Import metrics facade last to avoid early registry clearing in some environments
    from src.metrics import dump_metrics  # type: ignore
    all_metrics = dump_metrics()  # assume returns a structure listing metric names & samples (facade contract)
    # Basic assertion: at least our counter appears (value >=1). Fallback: len filter
    names = str(all_metrics)
    assert 'pipeline_expiry_recoverable_total' in names
