import os, re, sys, importlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Ensure src importable
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.metrics.spec import METRIC_SPECS, GROUPED_METRIC_SPECS  # type: ignore

CATALOG = ROOT / 'docs' / 'METRICS_CATALOG.md'

def test_catalog_exists():
    assert CATALOG.exists(), 'METRICS_CATALOG.md not generated; run scripts/gen_metrics_catalog.py'


def test_all_spec_metrics_listed():
    content = CATALOG.read_text(encoding='utf-8')
    # Build a set of expected metric names (Prom names)
    expected = {m.name for m in METRIC_SPECS + GROUPED_METRIC_SPECS}
    missing = [n for n in sorted(expected) if n not in content]
    assert not missing, f"Missing metric names in catalog: {missing}"


def test_markdown_table_format():
    content = CATALOG.read_text(encoding='utf-8').splitlines()
    # Basic sanity: header line and separator
    assert any(l.startswith('Attr | Prom Name |') for l in content), 'Header row missing'
    assert any(re.match(r'^--- \| ---', l) for l in content), 'Separator row missing'
