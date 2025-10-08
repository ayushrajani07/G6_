import json, subprocess, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / 'scripts' / 'gen_dashboards_modular.py'
OUT = ROOT / 'grafana' / 'dashboards' / 'generated'
CFG = ROOT / 'explorer_config.json'

def run(cmd, env=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    proc = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True, env=e)
    return proc.returncode, proc.stdout, proc.stderr

def test_explorer_config_override_band_pct(tmp_path):
    # Write a custom config with a distinct band_pct
    cfg_data = {'band_pct': 33}
    CFG.write_text(json.dumps(cfg_data))
    try:
        code, _, err = run([str(GEN), '--output', str(OUT), '--only', 'multi_pane_explorer_ultra'])
        assert code == 0, f'generation failed: {err}'
        path = OUT / 'multi_pane_explorer_ultra.json'
        assert path.exists(), 'dashboard JSON missing'
        data = json.loads(path.read_text())
        meta = data.get('g6_meta', {})
        # Verify metadata reflects override
        assert meta.get('band_pct') == 33, f"band_pct meta mismatch: {meta.get('band_pct')}"
        # Inspect histogram window anomaly band targets for % factor 0.33
        panels = data.get('panels', [])
        window = next(p for p in panels if p.get('g6_meta', {}).get('explorer_kind') == 'histogram_window')
        exprs = {t['refId']: t['expr'] for t in window['targets']}
        assert '0.330000' in exprs['C'] and '0.330000' in exprs['D'], f"band factor not applied in expressions: {exprs}"
    finally:
        # Cleanup config to avoid leaking into other tests
        if CFG.exists():
            CFG.unlink()
