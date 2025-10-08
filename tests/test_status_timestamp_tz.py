def test_status_timestamp_is_timezone_aware(run_mock_cycle):
    data = run_mock_cycle(cycles=1, interval=1)
    ts = data['timestamp']
    assert ts.endswith('Z') or ('+' in ts[-6:] and ts[-3] == ':'), f"Timestamp not timezone-aware: {ts}"
import json, os, tempfile, subprocess, sys
import pytest
from tests._helpers import fast_mode

@pytest.mark.slow
def test_runtime_status_timestamp_is_utc_z():
    status_path = os.path.join(tempfile.gettempdir(), 'g6_status_tz.json')
    env = os.environ.copy(); env['G6_USE_MOCK_PROVIDER']='1'
    # Use orchestrator runner script; run a single cycle by setting G6_LOOP_MAX_CYCLES=1
    env['G6_LOOP_MAX_CYCLES'] = '1'
    interval = '0.2' if fast_mode() else '1'
    cmd = [sys.executable, 'scripts/run_orchestrator_loop.py', '--config', 'config/g6_config.json', '--interval', interval, '--cycles', '1']
    subprocess.run(cmd, check=True, env=env)
    with open(status_path) as f:
        data = json.load(f)
    ts = data.get('timestamp')
    assert isinstance(ts, str) and ts.endswith('Z')
    # Basic parse check
    from datetime import datetime, timezone
    parsed = datetime.fromisoformat(ts.replace('Z','+00:00'))
    assert parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) == timezone.utc.utcoffset(parsed)
