from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_env_catalog_generated():
    path = ROOT / 'docs' / 'ENV_VARS_CATALOG.md'
    assert path.exists(), 'Run scripts/gen_env_catalog.py to generate ENV_VARS_CATALOG.md'
    text = path.read_text(encoding='utf-8')
    # Basic header sanity
    assert 'Environment Variables Catalog' in text.splitlines()[0]
    # Spot check a few known variables
    for name in ['G6_ENABLE_METRIC_GROUPS', 'G6_CATALOG_TS', 'G6_ESTIMATE_IV']:
        assert name in text, f'{name} missing from env vars catalog'


def test_config_catalog_generated():
    path = ROOT / 'docs' / 'CONFIG_KEYS_CATALOG.md'
    assert path.exists(), 'Run scripts/gen_config_catalog.py to generate CONFIG_KEYS_CATALOG.md'
    text = path.read_text(encoding='utf-8')
    assert 'Configuration Keys Catalog' in text.splitlines()[0]
    # Spot check a couple dotted keys
    for key in ['storage.csv_dir', 'kite.instrument_cache_path', 'orchestration.run_interval_sec']:
        assert key in text, f'{key} missing from config keys catalog'
