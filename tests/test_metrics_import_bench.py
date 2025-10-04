import json, subprocess, sys, pathlib

SCRIPT = 'scripts/metrics_import_bench.py'

def test_import_bench_json_output(tmp_path):
    proc = subprocess.run([sys.executable, SCRIPT, '--runs', '2', '--json'], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data['schema'] == 'g6.metrics.import_bench.v0'
    assert data['runs'] == 2
    assert len(data['samples_sec']) == 2
    assert 'stats' in data and 'p50_sec' in data['stats']
