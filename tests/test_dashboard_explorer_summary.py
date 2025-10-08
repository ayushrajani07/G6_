import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen_dashboards_modular.py"
OUT = ROOT / "grafana" / "dashboards" / "generated"


def run(cmd):
    proc = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_explorer_histogram_summary_panel():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"])
    assert code == 0, f"generation failed: {err}"
    data = json.loads((OUT / "multi_pane_explorer.json").read_text())
    panels = data.get("panels", [])
    summary_panel = next((p for p in panels if p.get("g6_meta", {}).get("explorer_kind") == "histogram_summary"), None)
    assert summary_panel, "histogram summary panel missing"
    targets = {t.get("expr") for t in summary_panel.get("targets", [])}
    assert any(":$q_5m" in e for e in targets), "missing $q_5m expr in summary"
    assert any(":$q_30m" in e for e in targets), "missing $q_30m expr in summary"
    assert any(":$q_ratio_5m_30m" in e for e in targets), "missing ratio expr in summary"
