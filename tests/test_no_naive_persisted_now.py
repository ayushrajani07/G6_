from pathlib import Path
import re

# We allow datetime.now() when it is:
# 1. Clearly timezone-aware: now(datetime.timezone.utc) or now(UTC)
# 2. In display-only contexts annotated with comment '# local-ok'
# 3. In timeutils module itself
# Everything else is flagged.

NAIVE_PATTERN = re.compile(r"datetime\.now\(\)")

ALLOWED_DISPLAY_COMMENT = '# local-ok'


def test_no_naive_persisted_now():
    repo_root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in repo_root.rglob('*.py'):
        low = str(path).lower()
        if '.venv' in low or 'site-packages' in low:
            continue
        if 'tests' in low:
            continue
        if '\\scripts\\hooks\\' in low or '/scripts/hooks/' in low:
            continue
        if path.name in {'timeutils.py','ci_time_guard.py'}:
            continue
        text = path.read_text(encoding='utf-8', errors='ignore')
        for m in NAIVE_PATTERN.finditer(text):
            # Extract line
            line_start = text.rfind('\n', 0, m.start()) + 1
            line_end = text.find('\n', m.end())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            if ALLOWED_DISPLAY_COMMENT in line:
                continue
            offenders.append(f"{path}:{line.strip()}")
    assert not offenders, 'Naive datetime.now() without timezone or annotation found: ' + '\n'.join(offenders)
