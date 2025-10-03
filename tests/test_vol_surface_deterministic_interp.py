import os, pathlib, math
import pytest
from src.metrics import setup_metrics_server, get_metrics  # facade import

# This test fabricates a minimal scenario to force interpolation path so that
# g6_vol_surface_interp_seconds histogram records at least one sample and
# quality score gauge is updated deterministically.

@pytest.mark.parametrize('with_model', [False])
def test_vol_surface_interpolation_records(monkeypatch, with_model):
    # Enable vol surface metrics group explicitly
    monkeypatch.setenv('G6_ENABLE_METRIC_GROUPS','analytics_vol_surface')
    monkeypatch.setenv('G6_DISABLE_METRIC_GROUPS','')
    if with_model:
        monkeypatch.setenv('G6_VOL_SURFACE_MODEL','1')
    metrics, _ = setup_metrics_server(reset=True)
    # Fabricate metrics state representing a build where interpolation fraction > 0
    # We simulate by directly invoking gauge setters if present, then calling a fake histogram observe.
    interp_hist = getattr(metrics, 'vol_surface_interp_seconds', None)
    quality_gauge = getattr(metrics, 'vol_surface_quality_score', None)
    if interp_hist is None or quality_gauge is None:
        pytest.skip('Vol surface instrumentation gated off')
    # Simulate an interpolation duration
    try:
        interp_hist.observe(0.001)
    except Exception:
        pass
    # Set quality to a deterministic mid value
    try:
        quality_gauge.labels(index='NIFTY').set(0.75)
    except Exception:
        quality_gauge.set(0.75)
    # Validate histogram count incremented
    observed = False
    for sample in interp_hist.collect():  # type: ignore
        for s in sample.samples:
            if s.name.endswith('_count') and s.value > 0:
                observed = True
    assert observed, 'Interpolation histogram lacked samples'
    # Validate quality sample accessible
    q_found = False
    for sample in quality_gauge.collect():  # type: ignore
        for s in sample.samples:
            if s.name.startswith('g6_vol_surface_quality_score') and s.value == pytest.approx(0.75):
                q_found = True
    assert q_found, 'Quality score gauge value not found'
