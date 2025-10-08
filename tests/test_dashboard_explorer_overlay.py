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


def test_explorer_overlay_variable_and_target():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"])
    assert code == 0, f"generation failed: {err}"
    data = json.loads((OUT / "multi_pane_explorer.json").read_text())
    tmpl = data.get("templating", {}).get("list", [])
    overlay_var = next((v for v in tmpl if v.get("name") == "overlay"), None)
    assert overlay_var, "overlay variable missing"
    assert overlay_var.get("query") == "off,fast,ultra"
    # Raw panel should have overlay targets (refIds C for 30s, D for 15s, E for smoothed) – presence unconditional; expressions gate via variable
    raw_panel = next((p for p in data.get("panels", []) if p.get("title") == "$metric raw & 5m rate"), None)
    assert raw_panel, "raw panel missing"
    refs = {t.get("refId") for t in raw_panel.get("targets", [])}
    for r in ["C","D","E"]:
        assert r in refs, f"overlay target refId {r} missing"
    # Sanity check expressions include gating overlay variable tokens
    expr_map = {t.get("refId"): t.get("expr") for t in raw_panel.get("targets", [])}
    assert "($overlay == 'fast')" in expr_map["C"] or "($overlay == 'ultra')" in expr_map["C"], "C expression missing overlay gating"
    assert "($overlay == 'ultra')" in expr_map["D"], "D expression missing ultra gating"
    assert "avg_over_time" in expr_map["E"], "E expression should include smoothing"
