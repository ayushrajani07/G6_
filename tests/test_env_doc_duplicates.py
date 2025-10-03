from pathlib import Path
import re

doc_path = Path('docs/env_dict.md')

# Regex capturing canonical env var tokens (G6_* uppercase style)
ENV_PATTERN = re.compile(r'\bG6_[A-Z0-9_]+\b')


def test_no_duplicate_env_var_documentation():
    assert doc_path.exists(), "env_dict.md missing"
    text = doc_path.read_text(encoding='utf-8')

    # Extract only lines that look like documentation entries (skip plain token reference blocks or removed markers)
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith('#')]

    occurrences = {}
    for line in lines:
        # Skip lines that intentionally show historical removed flags in parentheses
        if line.startswith('('):
            continue
        for match in ENV_PATTERN.findall(line):
            occurrences.setdefault(match, 0)
            occurrences[match] += 1

    dups = [name for name, count in occurrences.items() if count > 1]
    # Allow a curated small allowlist for known deliberate duplicate notes, if needed
    ALLOWLIST = set()  # populate if a deliberate duplicate is discovered
    offending = [d for d in dups if d not in ALLOWLIST]
    assert not offending, f"Duplicate environment variable docs detected: {offending}. Consolidate entries in env_dict.md."
