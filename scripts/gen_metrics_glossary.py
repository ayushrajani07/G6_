#!/usr/bin/env python3
"""Generate Metrics Glossary section in README.md.

Parses `src/metrics/metrics.py` for lines beginning with `# METRIC:` and
constructs a markdown table with metric name, description (following comment
lines until blank), and notes if always-on.

Usage:
  python scripts/gen_metrics_glossary.py [--write]

Without --write it prints the generated section to stdout (dry run).
With --write it updates README.md in-place between the markers:
  <!-- METRICS_GLOSSARY_START --> ... <!-- METRICS_GLOSSARY_END -->
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METRICS_FILE = ROOT / 'src' / 'metrics' / 'metrics.py'
README_FILE = ROOT / 'README.md'
START_MARK = '<!-- METRICS_GLOSSARY_START -->'
END_MARK = '<!-- METRICS_GLOSSARY_END -->'

def parse_metrics() -> list[dict]:
    text = METRICS_FILE.read_text(encoding='utf-8').splitlines()
    metrics: list[dict] = []
    i = 0
    while i < len(text):
        line = text[i].rstrip()
        if '# METRIC:' in line:
            # Extract metric identifiers (could be multiple separated by /)
            after = line.split('# METRIC:',1)[1].strip()
            id_part = after.split()[0]
            metric_ids = [m.strip() for m in id_part.split('/') if m.strip()]
            # Collect description lines until blank or new METRIC tag
            desc_lines: list[str] = []
            j = i + 1
            while j < len(text):
                nxt = text[j].rstrip()
                if not nxt.strip():
                    break
                if '# METRIC:' in nxt:
                    break
                if nxt.lstrip().startswith('#'):
                    desc_lines.append(nxt.lstrip().lstrip('#').strip())
                    j += 1
                    continue
                break
            description = ' '.join(desc_lines).strip()
            for mid in metric_ids:
                metrics.append({'id': mid, 'description': description})
            i = j
            continue
        i += 1
    return metrics

def load_always_on() -> set[str]:
    # Naive parse for _always_on_metrics append calls
    text = METRICS_FILE.read_text(encoding='utf-8')
    pattern = re.compile(r"self._always_on_metrics.append\('(.*?)'\)")
    return set(pattern.findall(text))

def build_markdown(metrics: list[dict]) -> str:
    always_on = load_always_on()
    header = '### Metrics Glossary (Auto-Generated)\n'
    header += '_The section below is managed by `scripts/gen_metrics_glossary.py`. Do not edit manually._\n\n'
    if not metrics:
        header += '_No metric annotations found._\n'
        return header
    lines = [header, '| Metric | Always On | Description |', '|--------|-----------|-------------|']
    seen = set()
    for m in metrics:
        mid = m['id']
        if mid in seen:
            continue
        seen.add(mid)
        desc = m['description'] or ''
        flag = 'yes' if mid in always_on else ''
        lines.append(f"| `{mid}` | {flag} | {desc} |")
    return '\n'.join(lines) + '\n'

def update_readme(md: str) -> None:
    content = README_FILE.read_text(encoding='utf-8')
    if START_MARK not in content or END_MARK not in content:
        print('Markers not found in README.md; aborting.', file=sys.stderr)
        sys.exit(1)
    new_section = f"{START_MARK}\n{md}{END_MARK}"
    # Replace greedily between markers
    content = re.sub(f"{re.escape(START_MARK)}.*?{re.escape(END_MARK)}", new_section, content, flags=re.DOTALL)
    README_FILE.write_text(content, encoding='utf-8')


def main(argv: list[str]) -> int:
    metrics = parse_metrics()
    md = build_markdown(metrics)
    if '--write' in argv:
        update_readme(md)
        print('README.md updated.')
    else:
        print(md)
    return 0

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
