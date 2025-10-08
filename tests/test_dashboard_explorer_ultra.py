import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / 'scripts' / 'gen_dashboards_modular.py'
OUT = ROOT / 'grafana' / 'dashboards' / 'generated'

def run(cmd):
    proc = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr

def test_explorer_ultra_dashboard_generated():
    code, _, err = run([str(GEN), '--output', str(OUT), '--only', 'multi_pane_explorer_ultra'])
    assert code == 0, f'generation failed: {err}'
    path = OUT / 'multi_pane_explorer_ultra.json'
    assert path.exists(), 'ultra explorer dashboard JSON missing'
    data = json.loads(path.read_text())
    meta = data.get('g6_meta', {})
    assert meta.get('ultra') is True, 'g6_meta.ultra flag should be true'
    panels = data.get('panels', [])
    # Ultra: 2 base timeseries + 1 summary + 1 histogram window = 4
    assert len(panels) == 4, f'expected 4 panels in ultra explorer, got {len(panels)}'
    titles = {p.get('title') for p in panels}
    # Ensure ratio & cumulative standalone panels absent
    assert not any('rate ratio' in t for t in titles), 'ratio panel should be folded into summary in ultra'
    assert not any('cumulative total' in t for t in titles), 'cumulative panel should be folded into summary in ultra'
    summary = next((p for p in panels if p.get('g6_meta', {}).get('explorer_kind') == 'histogram_summary'), None)
    assert summary, 'summary panel missing'
    # Ensure extra columns E (rate ratio) and F (cumulative) present in summary targets
    refs = {t.get('refId') for t in summary.get('targets', [])}
    for ref in ['E','F']:
        assert ref in refs, f'summary missing folded refId {ref}'
    # Verify band pct surfaced in metadata
    assert 'band_pct' in meta and isinstance(meta['band_pct'], (int,float)), 'band_pct metadata missing'
