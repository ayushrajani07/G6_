import warnings

from src.orchestrator.facade import run_collect_cycle

def test_pipeline_flag_emits_deprecation(monkeypatch):
    monkeypatch.setenv('G6_PIPELINE_COLLECTOR','1')
    monkeypatch.delenv('G6_LEGACY_COLLECTOR', raising=False)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter('always', DeprecationWarning)
        # providers=None triggers early path; we only care about warning emission.
        run_collect_cycle(index_params={}, providers=None, csv_sink=None, influx_sink=None, metrics=None, mode='auto')
        msgs = [str(x.message) for x in w if issubclass(x.category, DeprecationWarning)]
    assert any('G6_PIPELINE_COLLECTOR' in m for m in msgs), 'Expected deprecation warning for G6_PIPELINE_COLLECTOR'
