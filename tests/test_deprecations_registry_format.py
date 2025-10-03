import re, pathlib

REGEX_ROW = re.compile(r'^\|\s*`?[^|`]+`?\s*\|')


def test_deprecations_registry_tables_present():
    path = pathlib.Path('docs/DEPRECATIONS.md')
    text = path.read_text(encoding='utf-8')
    # Ensure required section headers exist
    for header in ('Deprecated Execution Paths', 'Environment Flag Deprecations', 'Removal Preconditions'):
        assert header in text, f'Missing section header: {header}'
    # Basic table row presence: run_live remains until its own removal; unified_main may have moved to Historical section post-removal.
    assert '`scripts/run_live.py`' in text
    # Planned Removal pattern R+N present
    assert 'R+2' in text, 'Expected R+2 removal horizon markers'


def test_deprecations_no_duplicate_component_rows():
    path = pathlib.Path('docs/DEPRECATIONS.md')
    lines = path.read_text(encoding='utf-8').splitlines()
    components = []
    for ln in lines:
        if ln.startswith('| `unified_main.collection_loop`') or ln.startswith('| `scripts/run_live.py`'):
            parts = [p.strip() for p in ln.strip('|').split('|')]
            if parts:
                components.append(parts[0])
    # Should only have one row per component
    assert len(components) == len(set(components)), f'Duplicate component rows found: {components}'
