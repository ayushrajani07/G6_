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


def test_explorer_compact_dashboard_generated():
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", "multi_pane_explorer_compact"])
    assert code == 0, f"generation failed: {err}"
    path = OUT / "multi_pane_explorer_compact.json"
    assert path.exists(), "compact explorer dashboard JSON missing"
    data = json.loads(path.read_text())
    assert data.get("title").startswith("Multi-Pane Explorer"), "title mismatch"
    panels = data.get("panels", [])
    # Compact: baseline 3 base TS + summary + histogram window = 5; optional panels may increase count.
    assert len(panels) >= 5, f"expected at least 5 panels in compact explorer, got {len(panels)}"
    titles = {p.get("title") for p in panels}
    assert not any("cumulative total" in t for t in titles), "cumulative panel should be removed in compact variant"
    # Heights reduced to 6 for base timeseries panels
    ts_panels = [p for p in panels if p.get("type") == "timeseries" and p.get("repeat") == "metric"]
    assert ts_panels, "no metric timeseries panels found"
    for p in ts_panels:
        assert p.get("gridPos", {}).get("h") == 6, "expected reduced height=6 for compact base panels"
    meta = data.get("g6_meta", {})
    assert meta.get("compact") is True, "g6_meta.compact flag should be true"
    # Delta threshold override present (byRegexp .*D$). Just ensure property exists.
    summary = next((p for p in panels if p.get("g6_meta", {}).get("explorer_kind") == "histogram_summary"), None)
    assert summary, "summary panel missing"
    overrides = summary.get("fieldConfig", {}).get("overrides", [])
    delta_override = next((o for o in overrides if o.get("matcher", {}).get("options") == ".*D$"), None)
    assert delta_override, "delta thresholds override missing in compact variant"
