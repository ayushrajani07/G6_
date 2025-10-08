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


def test_explorer_quantile_variable_and_targets():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"])
    assert code == 0, f"generation failed: {err}"
    data = json.loads((OUT / "multi_pane_explorer.json").read_text())
    tmpl = data.get("templating", {}).get("list", [])
    q_var = next((v for v in tmpl if v.get("name") == "q"), None)
    assert q_var, "quantile variable missing"
    query = q_var.get("query") or ""
    # Expect at least one quantile option and include p95 if available in recording rules
    parts = [p for p in query.split(",") if p]
    assert parts, "quantile list should not be empty"
    if "p95" in parts:
        # Ensure default selection is p95
        cur = q_var.get("current", {}).get("value")
        assert cur == "p95", "p95 should be selected by default when available"
    # Find histogram window panel template and verify expressions contain $q_5m/$q_30m
    hist_panel = next((p for p in data.get("panels", []) if p.get("g6_meta", {}).get("explorer_kind") == "histogram_window"), None)
    assert hist_panel, "histogram window panel missing"
    exprs = {t.get("expr") for t in hist_panel.get("targets", [])}
    assert any("$q_5m" in e for e in exprs), "expected $q_5m in histogram window panel targets"
    assert any("$q_30m" in e for e in exprs), "expected $q_30m in histogram window panel targets"
