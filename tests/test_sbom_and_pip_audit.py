import json, os, sys, subprocess, pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


def _run_script(rel_path, *args):
    script = REPO_ROOT / rel_path
    cmd = [sys.executable, str(script), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def test_gen_sbom_basic(tmp_path):
    # create a tiny requirements file
    req = tmp_path / 'requirements.txt'
    req.write_text('jsonschema==4.17.3')
    rc, out, err = _run_script('scripts/gen_sbom.py', '--requirements', str(req), '--output', str(tmp_path / 'sbom.json'))
    assert rc == 0, out + err
    data = json.loads((tmp_path / 'sbom.json').read_text())
    assert 'components' in data and isinstance(data['components'], list)


def test_pip_audit_gate_offline_pass(tmp_path):
    # Simulated pip-audit JSON with only LOW severity and gate HIGH
    audit_json = tmp_path / 'audit.json'
    audit_json.write_text(json.dumps([
        {"name": "foo", "version": "1.0", "vulns": [
            {"id":"VULN-1","severity":"LOW","fix_versions":[]}
        ]}
    ]))
    rc, out, err = _run_script('scripts/pip_audit_gate.py', '--input', str(audit_json), '--max-severity', 'HIGH')
    assert rc == 0, out + err


def test_pip_audit_gate_offline_fail(tmp_path):
    audit_json = tmp_path / 'audit.json'
    audit_json.write_text(json.dumps([
        {"name": "bar", "version": "2.0", "vulns": [
            {"id":"VULN-2","severity":"CRITICAL","fix_versions":["2.1"]}
        ]}
    ]))
    rc, out, err = _run_script('scripts/pip_audit_gate.py', '--input', str(audit_json), '--max-severity', 'HIGH')
    assert rc != 0  # should fail due to CRITICAL >= HIGH threshold
    assert 'FAIL' in out
