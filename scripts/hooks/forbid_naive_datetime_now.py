#!/usr/bin/env python3
import pathlib
import re
import sys

# Detect datetime.now() not followed by (timezone.utc) or tz= and not part of allowed comment
PATTERN = re.compile(r"datetime\.now\s*\(\s*\)")
ALLOWED_COMMENT = '# fallback (tz-aware source)'

def main() -> int:
    offenders = []
    for path in sys.argv[1:]:
        p = pathlib.Path(path)
        try:
            text = p.read_text(encoding='utf-8')
        except Exception:
            continue
        token = 'datetime.' + 'now('
        if token not in text:
            continue
        for m in PATTERN.finditer(text):
            # Extract surrounding line
            line_start = text.rfind('\n', 0, m.start()) + 1
            line_end = text.find('\n', m.end())
            if line_end == -1:
                line_end = len(text)
            line = text[line_start:line_end]
            if 'timezone.utc' in line or 'tz=' in line:
                continue
            if ALLOWED_COMMENT in line:
                continue
            offenders.append(f"{p}:{line.strip()}")
    if offenders:
        print('ERROR: naive datetime.now() detected (missing timezone):')
        for o in offenders:
            print('  -', o)
        print('Use datetime.now(timezone.utc) or get_ist_now()/utc_now() from utils/timeutils.')
        return 1
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
