import logging, re, os
from contextlib import contextmanager

import pytest

# We will import bootstrap and run bootstrap_runtime with a minimal config path.
# Use an existing small config fixture or generate a temporary minimal config file.

@pytest.fixture()
def minimal_config_file(tmp_path):
    # Build a config conforming to schema (version, application, metrics, collection, storage, indices, features, console)
    cfg = {
        "version": "2.0",
        "application": "testapp",
        "metrics": {"port": 9108, "host": "127.0.0.1"},
        "collection": {"interval_seconds": 1},
        "storage": {"csv_dir": str(tmp_path / "csv")},
        # Minimal single index config with required fields (enable, strikes_itm, strikes_otm, expiries)
        "indices": {
            "NIFTY": {"enable": True, "strikes_itm": 1, "strikes_otm": 1, "expiries": ["2025-12-31"]},
            "BANKNIFTY": {"enable": True, "strikes_itm": 1, "strikes_otm": 1, "expiries": ["2025-12-31"]},
        },
        "features": {"analytics_startup": False},
        "console": {"fancy_startup": False, "live_panel": False, "startup_banner": False, "force_ascii": True, "runtime_status_file": ""},
        # Allow storage path creation expectations to pass silently
    }
    import json
    p = tmp_path / "config.json"
    p.write_text(json.dumps(cfg))
    return str(p)

@contextmanager
def capture_logs(match_logger: str):
    logger = logging.getLogger(match_logger)
    old_level = logger.level
    logger.setLevel(logging.INFO)
    from io import StringIO
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    try:
        yield stream
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)


def test_orchestrator_summary_structured_once(monkeypatch, minimal_config_file):
    # Ensure sentinel in bootstrap module not present (remove if earlier test imported bootstrap)
    try:
        import src.orchestrator.bootstrap as boot  # type: ignore
        if '_G6_ORCH_SUMMARY_EMITTED' in boot.__dict__:
            del boot.__dict__['_G6_ORCH_SUMMARY_EMITTED']
    except Exception:
        pass
    # Clear env that could interfere
    for k in list(os.environ.keys()):
        if k.startswith('G6_'):
            # Keep config path unrelated envs
            pass
    from src.orchestrator import bootstrap
    with capture_logs('src.orchestrator.bootstrap') as s:
        bootstrap.bootstrap_runtime(minimal_config_file)
        out = s.getvalue()
    assert out.count('orchestrator.summary') == 1, out
    # Re-run to confirm no duplicate
    with capture_logs('src.orchestrator.bootstrap') as s2:
        bootstrap.bootstrap_runtime(minimal_config_file)
        out2 = s2.getvalue()
    assert 'orchestrator.summary' not in out2


def test_orchestrator_human_summary(monkeypatch, minimal_config_file):
    monkeypatch.setenv('G6_ORCH_SUMMARY_HUMAN','1')
    from src.orchestrator import bootstrap
    if '_G6_ORCH_SUMMARY_EMITTED' in vars(bootstrap):
        del bootstrap.__dict__['_G6_ORCH_SUMMARY_EMITTED']
    with capture_logs('src.orchestrator.bootstrap') as s:
        bootstrap.bootstrap_runtime(minimal_config_file)
        out = s.getvalue()
    assert 'ORCHESTRATOR SUMMARY' in out
    # Basic field presence
    assert 'loop_interval' in out
    assert 'indices_count' in out
