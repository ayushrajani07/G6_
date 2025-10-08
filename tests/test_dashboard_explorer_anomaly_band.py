import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / 'scripts' / 'gen_dashboards_modular.py'
OUT = ROOT / 'grafana' / 'dashboards' / 'generated'

def run(cmd):
    proc = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_histogram_window_has_band_targets():
    code, _, err = run([str(GEN), '--output', str(OUT), '--only', 'multi_pane_explorer'])
    assert code == 0, f'generation failed: {err}'
    data = json.loads((OUT / 'multi_pane_explorer.json').read_text())
    panels = data.get('panels', [])
    window = next((p for p in panels if p.get('g6_meta', {}).get('explorer_kind') == 'histogram_window'), None)
    assert window, 'histogram window panel missing'
    refs = {t.get('refId') for t in window.get('targets', [])}
    for ref in ['A','B','C','D']:
        assert ref in refs, f'missing anomaly band refId {ref}'
    expr_map = {t.get('refId'): t.get('expr') for t in window.get('targets', [])}
    # Expressions now embed a constant factor (default 0.20) derived from config/env precedence
    assert '* (1 - 0.20' in expr_map['C'] or '* (1 - 0.2' in expr_map['C'], 'lower band should embed 20% constant'
    assert '* (1 + 0.20' in expr_map['D'] or '* (1 + 0.2' in expr_map['D'], 'upper band should embed 20% constant'
