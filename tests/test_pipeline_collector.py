import os, json, pathlib, importlib
import pytest

pytestmark = pytest.mark.serial

def test_pipeline_basic(monkeypatch, tmp_path):
    """Enable pipeline flag and ensure run_cycle executes without raising.

    We rely on fallback provider methods being present; if real providers are not
    configured the pipeline should still complete quickly with warnings.
    """
    os.environ['G6_PIPELINE_COLLECTOR'] = '1'
    os.environ['G6_FORCE_MARKET_OPEN'] = '1'  # bypass market hours if legacy checks appear
    # Lazy import bootstrap + cycle
    import pytest
    from src.orchestrator.bootstrap import bootstrap_runtime
    from src.orchestrator.cycle import run_cycle
    try:
        ctx, _stop = bootstrap_runtime('config/g6_config.json')
    except RuntimeError as e:
        pytest.skip(f"bootstrap runtime unavailable: {e}")
    # Provide minimal index_params if absent
    if ctx.index_params is None:
        idx = ctx.config.get('index_params') or {
            'NIFTY': { 'expiries': ['this_week'], 'strikes_itm': 2, 'strikes_otm': 2, 'enable': True }
        }
        ctx.index_params = idx  # type: ignore
    elapsed = run_cycle(ctx)  # type: ignore[arg-type]
    assert isinstance(elapsed, float)
    assert elapsed >= 0.0
    # Disable flag for other tests
    os.environ.pop('G6_PIPELINE_COLLECTOR', None)
