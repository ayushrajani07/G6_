import json, tempfile, os, subprocess, sys, textwrap

def write_events(lines):
    fd, path = tempfile.mkstemp(text=True)
    with os.fdopen(fd,'w', encoding='utf-8') as f:
        for line in lines:
            f.write(json.dumps(line) + '\n')
    return path

def run_script(path, *args):
    cmd = [sys.executable, 'scripts/check_integrity.py', '--events-file', path, *args]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode, res.stdout.strip(), res.stderr.strip()


def test_no_gaps():
    events = [ {'event':'cycle_start','context':{'cycle':i}} for i in range(5) ]
    p = write_events(events)
    code, out, err = run_script(p)
    assert code == 0, err
    data = json.loads(out)
    assert data['missing_count'] == 0


def test_with_gaps():
    # cycles: 0,1,2,5 -> gaps 3,4 => 2 missing
    events = [ {'event':'cycle_start','context':{'cycle':i}} for i in (0,1,2,5) ]
    p = write_events(events)
    code, out, err = run_script(p)
    assert code == 2, err
    data = json.loads(out)
    assert data['missing_count'] == 2
    assert data['status'] == 'GAPS'


def test_missing_file():
    code, out, err = run_script('nonexistent_events.log')
    assert code == 3
    assert 'ERROR: events file not found' in err or 'ERROR: events file not found' in out
