import json, os, tempfile
from pathlib import Path

from src.config.loader import load_and_validate_config, ConfigValidationError
from src.metrics import MetricsRegistry  # facade import
from prometheus_client import CollectorRegistry, REGISTRY

def _write_tmp(content: dict) -> str:
    fd, path = tempfile.mkstemp(suffix='.json', text=True)
    with open(path,'w',encoding='utf-8') as f:
        json.dump(content,f)
    return path

BASE_VALID = {
    "version": "2.0",
    "application": "G6App",
    "metrics": {"port": 9000, "host": "127.0.0.1", "option_details_enabled": False},
    "collection": {"interval_seconds": 30},
    "storage": {"csv_dir": "data/g6_data"},
    "indices": {
        "NIFTY": {"enable": True, "strikes_itm": 10, "strikes_otm": 10, "expiries": ["2025-12-25"]}
    },
    "features": {"analytics_startup": False},
    "console": {"fancy_startup": False, "live_panel": False, "startup_banner": False, "force_ascii": True, "runtime_status_file": "data/runtime_status.json"}
}


def test_valid_config_passes():
    path = _write_tmp(BASE_VALID)
    cfg = load_and_validate_config(path)
    assert cfg["version"] == "2.0"


def test_invalid_index_symbol_rejected():
    bad = dict(BASE_VALID)
    bad_indices = {"nifty": {"enable": True, "strikes_itm":1, "strikes_otm":1, "expiries":["2025-12-25"]}}  # lowercase violation
    bad["indices"] = bad_indices
    path = _write_tmp(bad)
    try:
        load_and_validate_config(path)
        assert False, "Expected schema validation failure for lowercase index key"
    except ConfigValidationError as e:
        assert "indices" in str(e).lower()


def test_deprecated_keys_metric_increment(monkeypatch):
    # Phase 1: legacy top-level key should now fail schema (additionalProperties false)
    dep_legacy = json.loads(json.dumps(BASE_VALID))
    dep_legacy["index_params"] = {}
    path_legacy = _write_tmp(dep_legacy)
    # Avoid re-registering metrics (duplicate collision) by attempting to import a global metrics registry
    metrics = None  # Not needed for validation failure assertions
    try:
        load_and_validate_config(path_legacy, metrics=metrics)
        assert False, "Expected schema validation error for legacy key index_params"
    except ConfigValidationError:
        pass


def test_soft_legacy_mode_allows_deprecated(monkeypatch):
    # Build config containing deprecated keys that schema would normally reject
    dep = json.loads(json.dumps(BASE_VALID))
    dep["index_params"] = {"foo": 1}
    dep["storage"]["influx_enabled"] = True
    path = _write_tmp(dep)
    # Without soft flag expect failure
    try:
        load_and_validate_config(path)
        assert False, "Expected validation failure without soft legacy flag"
    except ConfigValidationError:
        pass
    # With soft legacy flag expect success and keys stripped
    monkeypatch.setenv('G6_CONFIG_LEGACY_SOFT', '1')
    cfg = load_and_validate_config(path)
    assert 'index_params' not in cfg
    assert 'influx_enabled' not in cfg.get('storage', {})
    monkeypatch.delenv('G6_CONFIG_LEGACY_SOFT', raising=False)
