import json, os, tempfile, subprocess, sys

def test_runtime_status_timestamp_is_utc_z():
    status_path = os.path.join(tempfile.gettempdir(), 'g6_status_tz.json')
    env = os.environ.copy(); env['G6_USE_MOCK_PROVIDER']='1'
    cmd = [sys.executable, '-m', 'src.unified_main', '--run-once', '--runtime-status-file', status_path]
    subprocess.run(cmd, check=True, env=env)
    with open(status_path) as f:
        data = json.load(f)
    ts = data.get('timestamp')
    assert isinstance(ts, str) and ts.endswith('Z')
    # Basic parse check
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(ts.replace('Z','+00:00'))
    assert parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) == timezone.utc.utcoffset(parsed)
