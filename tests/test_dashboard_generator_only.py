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


def test_only_flag_generates_subset(tmp_path):
    # Ensure a clean full generation first
    code, _, err = run([str(GEN), "--output", str(OUT)])
    assert code == 0, f"full generation failed: {err}"
    manifest_path = OUT / "manifest.json"
    original = json.loads(manifest_path.read_text())
    full_counts = {d['slug']: d['panel_count'] for d in original['dashboards']}
    # Pick two slugs expected to exist
    subset = ["bus_health", "system_overview_minimal"]
    for s in subset:
        assert s in full_counts, f"expected slug {s} in full generation"
    # Run only generation
    code, _, err = run([str(GEN), "--output", str(OUT), "--only", ",".join(subset)])
    assert code == 0, f"only generation failed: {err}"
    updated = json.loads(manifest_path.read_text())
    counts_after = {d['slug']: d['panel_count'] for d in updated['dashboards']}
    # Selected slugs must retain their non-zero counts
    for s in subset:
        assert counts_after[s] == full_counts[s] and counts_after[s] > 0, f"subset slug {s} panel count changed unexpectedly"
    # Non-selected slugs should show 0 to signal skipping
    skipped = [k for k in full_counts if k not in subset]
    assert any(counts_after[k] == 0 for k in skipped), "expected at least one skipped dashboard to have zero count"
    # Restore full generation to leave workspace consistent
    code, _, err = run([str(GEN), "--output", str(OUT)])
    assert code == 0, f"restore generation failed: {err}"
