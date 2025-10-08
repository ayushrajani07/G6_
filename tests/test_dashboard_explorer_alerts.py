import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GEN = ROOT / "scripts" / "gen_dashboards_modular.py"
OUT = ROOT / "grafana" / "dashboards" / "generated"

def run(cmd):
    proc = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_explorer_alerts_panel_present():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"])
    assert code == 0, f"generation failed: {err}"
    data = json.loads((OUT / "multi_pane_explorer.json").read_text())
    panels = data.get("panels", [])
    alerts_panel = next((p for p in panels if p.get("g6_meta", {}).get("explorer_kind") == "alerts_context"), None)
    assert alerts_panel, "alerts context panel missing"
    exprs = [t.get("expr") for t in alerts_panel.get("targets", [])]
    assert any("ALERTS{alertstate='firing'}" in e for e in exprs), "alerts panel expression unexpected"


def test_explorer_alerts_disabled_env():
    # Disable via env var and ensure panel omitted
    env = dict(**{k: v for k, v in dict(**os.environ).items()})
    env["G6_EXPLORER_NO_ALERTS"] = "1"
    proc = subprocess.run([sys.executable, str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"], cwd=ROOT, capture_output=True, text=True, env=env)
    assert proc.returncode == 0, f"generation failed: {proc.stderr}"
    data = json.loads((OUT / "multi_pane_explorer.json").read_text())
    panels = data.get("panels", [])
    assert not any(p.get("g6_meta", {}).get("explorer_kind") == "alerts_context" for p in panels), "alerts context panel should be disabled"
