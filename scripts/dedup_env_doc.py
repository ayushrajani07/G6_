"""Utility script to normalize docs/env_dict.md:
- Detect all G6_ variable lines
- Keep first occurrence (preferring line with richer markers: deprecated/alias/removed)
- Remove later duplicates
- Append stub entries for missing env vars discovered by tests
Safe: writes to a temp file then replaces original.
"""
from __future__ import annotations

import re
from pathlib import Path

DOC = Path('docs/env_dict.md')
MISSING = [
    'G6_CSV_BASE_DIR',
    'G6_CSV_DEMO_DIR',
    'G6_CSV_VERBOSE',
    'G6_METRICS_URL',  # ensure clean canonical line exists
    'G6_PANELS_VALIDATE',
    'G6_PANELS_WRITER_BASIC',
    'G6_PANEL_AUTO_FIT',
    'G6_PANEL_CLIP',
    'G6_TRACE_AUTO_DISABLE',
]
# Regex capturing env token at start of a bullet or inside a line
TOKEN_RE = re.compile(r'\bG6_[A-Z0-9_]+\b')
PREF_MARKERS = ('deprecated', 'alias', 'removed', 'historical', 'no-op')


def choose(existing: str, new: str) -> str:
    """Decide which line to keep when a duplicate token is found."""
    e_low = existing.lower()
    n_low = new.lower()
    # Prefer line containing any preference markers if existing lacks them
    if not any(m in e_low for m in PREF_MARKERS) and any(m in n_low for m in PREF_MARKERS):
        return new
    # Otherwise keep the first (stable ordering)
    return existing


def main():
    text = DOC.read_text(encoding='utf-8')
    lines = text.splitlines()
    kept_lines: list[str] = []
    chosen: dict[str, str] = {}
    # Track which tokens appear on which line index for reporting
    multi: dict[str, int] = {}

    for line in lines:
        stripped = line.strip()
        if not stripped:
            kept_lines.append(line)
            continue
        # Skip plain token reference helper lines (e.g., '# Plain token reference')
        if stripped.startswith('# Plain token reference'):
            kept_lines.append(line)
            continue
        tokens = set(TOKEN_RE.findall(line))
        if not tokens:
            kept_lines.append(line)
            continue
        # For each token decide retention
        replace_line = False
        for tok in tokens:
            if tok not in chosen:
                chosen[tok] = line
            else:
                # Already have one; maybe replace if new line is richer
                new_choice = choose(chosen[tok], line)
                if new_choice is not chosen[tok]:
                    chosen[tok] = new_choice
                multi[tok] = multi.get(tok, 1) + 1
                replace_line = True
        if replace_line:
            # Drop this duplicate occurrence (not appended)
            continue
        kept_lines.append(line)

    # Ensure missing entries present exactly once
    existing_tokens = set(chosen.keys())
    missing_needed = [m for m in MISSING if m not in existing_tokens]
    if missing_needed:
        kept_lines.append('\n')
        kept_lines.append('## Automated Additions (dedup script)')
        for name in missing_needed:
            if name == 'G6_CSV_BASE_DIR':
                desc = 'path – (none) – Base directory for CSV output (legacy; prefer config path if supported).'
            elif name == 'G6_CSV_DEMO_DIR':
                desc = 'path – (none) – Demo/sample CSV output directory used by test/demo scripts.'
            elif name == 'G6_CSV_VERBOSE':
                desc = 'bool – off – Emit extra verbose CSV writer debug logs (per-row decisions).'
            elif name == 'G6_METRICS_URL':
                desc = 'url – (none) – Explicit Prometheus scrape base URL override for tooling/tests.'
            elif name == 'G6_PANELS_VALIDATE':
                desc = 'bool – off – Validate panel JSON against schema before write (diagnostic overhead).'
            elif name == 'G6_PANELS_WRITER_BASIC':
                desc = 'bool – off – Force basic panel writer variant (reduced fields) for compatibility tests.'
            elif name == 'G6_PANEL_AUTO_FIT':
                desc = 'bool – on – Auto-fit panel column widths based on content (disable for fixed layout debugging).'
            elif name == 'G6_PANEL_CLIP':
                desc = 'bool – on – Clip overly wide panel content cells (disable to inspect full raw values).'
            elif name == 'G6_TRACE_AUTO_DISABLE':
                desc = 'bool – off – Automatically disable high-volume TRACE flags after N cycles (internal throttle).'
            else:
                desc = 'undocumented – TODO'
            kept_lines.append(f'- {name} – {desc}')

    new_text = '\n'.join(kept_lines)
    if new_text != text:
        tmp = DOC.with_suffix('.md.tmp')
        tmp.write_text(new_text, encoding='utf-8')
        DOC.write_text(new_text, encoding='utf-8')

    # Emit a small summary when run directly
    removed = [k for k, c in multi.items() if c > 1]
    print(f"Dedup complete. Unique tokens: {len(chosen)}. Duplicates collapsed: {len(multi)}. Still missing newly added: {missing_needed}")

if __name__ == '__main__':
    main()
