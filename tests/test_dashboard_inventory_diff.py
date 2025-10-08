import subprocess, sys, json, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / 'scripts' / 'diff_dashboard_inventory.py'


def write_csv(path: Path, rows):
    import io
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['slug','title','metric','source','panel_uuid'])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run(args):
    proc = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_inventory_diff_added_removed_renamed(tmp_path):
    prev = tmp_path / 'prev.csv'
    curr = tmp_path / 'curr.csv'
    # Previous inventory: two panels
    write_csv(prev, [
        {'slug':'dash1','title':'Panel A','metric':'m1','source':'spec','panel_uuid':'1111aaaa2222bbbb'},
        {'slug':'dash1','title':'Panel B','metric':'m2','source':'spec','panel_uuid':'3333cccc4444dddd'},
    ])
    # Current: one removed (Panel B), one renamed (Panel A->Panel A Prime), one added new uuid
    write_csv(curr, [
        {'slug':'dash1','title':'Panel A Prime','metric':'m1','source':'spec','panel_uuid':'1111aaaa2222bbbb'},
        {'slug':'dash1','title':'Panel C','metric':'m3','source':'auto_rate','panel_uuid':'5555eeee6666ffff'},
    ])
    code, out, err = run([str(SCRIPT), str(prev), str(curr), '--json-out', str(tmp_path/'diff.json')])
    assert code == 7, f"expected diff exit 7, got {code}, stderr={err}"
    assert 'Added (1):' in out
    assert 'Removed (1):' in out
    assert 'Renamed (1):' in out
    diff_data = json.loads((tmp_path/'diff.json').read_text())
    assert len(diff_data['added']) == 1
    assert len(diff_data['removed']) == 1
    assert len(diff_data['renamed']) == 1
    assert diff_data['renamed'][0]['old_title'] == 'Panel B' or diff_data['renamed'][0]['old_title'] == 'Panel A', 'renamed detection mismatch'
