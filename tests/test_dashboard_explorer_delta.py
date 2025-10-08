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


def test_explorer_summary_delta_target():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"])
    assert code == 0, f"generation failed: {err}"
    data = json.loads((OUT / "multi_pane_explorer.json").read_text())
    summary_panel = next((p for p in data.get("panels", []) if p.get("g6_meta", {}).get("explorer_kind") == "histogram_summary"), None)
    assert summary_panel, "summary panel missing"
    targets = [t.get("expr") for t in summary_panel.get("targets", [])]
    delta_expr = next((e for e in targets if "- $metric_hist:$q_30m" in e and "/ clamp_min" in e), None)
    assert delta_expr, "delta expression missing"
