from pathlib import Path
import re

FORBIDDEN = 'datetime.utcnow('  # test token; DO NOT ALTER SUBSTRING SCAN -- replaced runtime usage elsewhere

def test_no_datetime_utcnow():
    repo_root = Path(__file__).resolve().parents[1]
    offenders = []
    self_path = Path(__file__).resolve()
    for path in repo_root.rglob('*.py'):
        # Skip virtual env or hidden dirs just in case
        pstr = str(path).lower()
        if '.venv' in pstr or 'site-packages' in pstr:
            continue
        if '\\scripts\\hooks\\' in pstr or '/scripts/hooks/' in pstr:
            # Hook scripts may intentionally reference forbidden tokens for enforcement logic
            continue
        if path == self_path or path.name == 'ci_time_guard.py':
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        if FORBIDDEN in text:
            offenders.append(str(path))
    assert not offenders, f"Forbidden datetime.utcnow() usage found in: {offenders}"