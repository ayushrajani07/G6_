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


def test_explorer_dashboard_generated():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer"])
    assert code == 0, f"generation failed: {err}"
    path = OUT / "multi_pane_explorer.json"
    assert path.exists(), "explorer dashboard JSON missing"
    data = json.loads(path.read_text())
    assert data.get("title") == "Multi-Pane Explorer"
    panels = data.get("panels", [])
    # Panel templates baseline: 4 base (raw/rate, rate 1m vs 5m, ratio, cumulative) + summary + histogram window = 6
    # Optional panels (inventory diff, alerts) may add +1 or +2. Accept >=6.
    assert len(panels) >= 6, f"expected at least 6 explorer panels, got {len(panels)}"
    # Ensure templating variable present
    tmpl = data.get("templating", {}).get("list", [])
    metric_var = next((v for v in tmpl if v.get("name") == "metric"), None)
    hist_var = next((v for v in tmpl if v.get("name") == "metric_hist"), None)
    assert metric_var, "metric templating variable missing"
    assert hist_var, "metric_hist templating variable missing"
    assert metric_var.get("multi") is True, "multi-select should be enabled now"
    assert hist_var.get("multi") is True, "histogram multi-select should be enabled"
    # Basic panel sanity: panel_uuid metadata present
    hist_window = 0
    hist_ratio = 0  # should remain 0 now (ratio panel removed)
    for p in panels:
        meta = p.get("g6_meta", {})
        assert meta.get("panel_uuid"), "panel_uuid missing on explorer panel"
        # Enforce repeat only for the core explorer template kinds
        if meta.get("explorer_kind") in {"histogram_summary", "histogram_window"} or p.get("title", "").startswith("$metric"):
            rep = p.get("repeat")
            assert rep in {"metric", "metric_hist"}, f"unexpected repeat value {rep}"
        if meta.get("explorer_kind") == "histogram_window":
            hist_window += 1
        if meta.get("explorer_kind") == "histogram_ratio":
            hist_ratio += 1
    # Expect exactly one histogram window and zero histogram ratio panels (ratio collapsed into summary)
    assert hist_window == 1 and hist_ratio == 0, "unexpected histogram panel counts"
