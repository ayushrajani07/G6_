import os, json, textwrap, importlib, types, sys, pathlib
from src.config.loader import load_and_validate_config, ConfigValidationError


def test_provider_capability_validation(tmp_path, monkeypatch):
    # Create a fake providers module with one provider missing a required method
    mod = types.ModuleType('src.providers')
    class GoodProvider:
        def get_index_data(self, index):
            return 0.0, None
        def get_option_chain(self, index, expiry):
            return []
    class BadProvider:
        def get_index_data(self, index):
            return 0.0, None
        # missing get_option_chain
    # Expose classes (capitalized) so capability validator introspection finds them.
    mod.GoodProvider = GoodProvider
    mod.BadProvider = BadProvider
    # Inject into sys.modules and attach to the already-imported src package (loader uses 'from src import providers').
    sys.modules['src.providers'] = mod
    import src  # type: ignore
    setattr(src, 'providers', mod)
    # Build a minimal schema-compliant config (schema_v2.json) so that we can reach
    # the provider capability validation stage. The schema requires many top-level
    # keys; we fill them with minimal valid values.
    cfg = {
        "version": "2.0",
        "application": "g6-test",
        "metrics": {"port": 9000, "host": "127.0.0.1"},
        "collection": {"interval_seconds": 60},
        "storage": {"csv_dir": "data/g6_data"},
        "features": {"analytics_startup": False},
        "indices": {
            # Use a concrete expiry date string matching the YYYY-MM-DD pattern
            "NIFTY": {"enable": True, "provider": "GoodProvider", "expiries": ["2025-12-31"], "strikes_itm": 2, "strikes_otm": 2},
            "BANKNIFTY": {"enable": True, "provider": "BadProvider", "expiries": ["2025-12-31"], "strikes_itm": 2, "strikes_otm": 2}
        },
        "console": {"fancy_startup": False, "live_panel": False, "startup_banner": False, "force_ascii": True, "runtime_status_file": "data/runtime_status.json"}
    }
    cfg_path = tmp_path / 'config.json'
    cfg_path.write_text(json.dumps(cfg))
    monkeypatch.setenv('G6_CONFIG_VALIDATE_CAPABILITIES','1')
    # Validation should raise due to BadProvider missing get_option_chain
    try:
        load_and_validate_config(str(cfg_path))
        assert False, 'Expected capability validation error'
    except ConfigValidationError as e:
        # Expect aggregated error containing missing method marker for BadProvider
        msg = str(e)
        assert 'E-PROV-MISSING:BANKNIFTY:BadProvider:get_option_chain' in msg

