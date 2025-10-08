import subprocess, sys, csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'export_dashboard_inventory.py'
GEN = ROOT / 'scripts' / 'gen_dashboards_modular.py'
OUT_DIR = ROOT / 'grafana' / 'dashboards' / 'generated'


def run(args):
    proc = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def ensure_generation():
    code, _, err = run([str(GEN), '--output', str(OUT_DIR)])
    assert code == 0, f'generator failed: {err}'


def test_inventory_csv_and_jsonl(tmp_path):
    ensure_generation()
    csv_path = tmp_path / 'inv.csv'
    code, out, err = run([str(SCRIPT), '--dir', str(OUT_DIR), '--out', str(csv_path), '--format', 'csv'])
    assert code == 0, f'csv export failed: {err}'
    rows = list(csv.DictReader(csv_path.open()))
    assert rows, 'no rows exported'
    for field in ['slug','title','metric','source','panel_uuid']:
        assert field in rows[0], f'missing field {field}'
    # JSONL
    jsonl_path = tmp_path / 'inv.jsonl'
    code, out, err = run([str(SCRIPT), '--dir', str(OUT_DIR), '--out', str(jsonl_path), '--format', 'jsonl', '--filter-source', 'spec'])
    assert code == 0, f'jsonl export failed: {err}'
    lines = jsonl_path.read_text().strip().splitlines()
    assert lines, 'no jsonl lines exported'
    sample = json.loads(lines[0])
    for k in ['slug','title','metric','source','panel_uuid']:
        assert k in sample
    assert sample['source'] == 'spec', 'filter-source not applied'
