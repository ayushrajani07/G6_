import re
import os
import json
from pathlib import Path
import pytest

# Basic template directory resolution (relative to this test file)
TEMPLATES_DIR = Path(__file__).parent.parent / 'src' / 'web' / 'dashboard' / 'templates'

TEMPLATE_FILES = [
    '_stream_fragment.html',
    '_footer_fragment.html',
    '_storage_fragment.html',
]

# Simplistic regex patterns to find snapshot.* chains (jinja variable usage)
VAR_PATTERN = re.compile(r'snapshot(?:\.[a-zA-Z0-9_]+)+')

# Construct minimal representative sample structures approximating runtime objects.
# These purposely include only keys referenced by current templates; if a template
# adds new keys this test will fail, guiding addition to typed layer / sample.

def build_sample_snapshot():
    return {
        'stream_rows': [
            {
                'time': '12:00:00', 'index': 'NIFTY', 'legs': 10, 'legs_avg': 10,
                'legs_cum': 100, 'succ': 95.0, 'succ_avg': 94.0, 'succ_life': 93.5,
                'cycle_attempts': 5.0, 'err': '', 'status': 'ok', 'status_reason': ''
            }
        ],
        'footer': {
            'total_legs': 10,
            'overall_success': 95.0,
            'indices': 1,
        },
        'storage': {
            'csv': {
                'files_total': 1, 'records_total': 100, 'records_delta': 5,
                'errors_total': 0, 'disk_mb': 1.2
            },
            'influx': {
                'points_total': 1000, 'points_delta': 10, 'write_success_pct': 99.0,
                'connection': 1, 'query_latency_ms': 12.5
            },
            'backup': {
                'files_total': 2, 'last_backup_unixtime': 1700000000,
                'age_seconds': 600, 'size_mb': 5.5
            }
        },
        'age_seconds': 3.2,
        'stale': False,
    }

# Enveloped footer variant (Wave 4 PoC) supplied separately in runtime; we include here
# to audit footer template fallback logic.
FOOTER_ENVELOPED = {
    'kind': 'footer',
    'footer': build_sample_snapshot()['footer']
}

@pytest.mark.parametrize('template_name', TEMPLATE_FILES)
def test_snapshot_variable_references_exist(template_name):
    path = TEMPLATES_DIR / template_name
    assert path.exists(), f"Template not found: {path}"
    text = path.read_text(encoding='utf-8')

    # Extract snapshot.* references (ignore those inside comments)
    refs = set(VAR_PATTERN.findall(text))
    # Normalise: snapshot.a.b -> tuple('a','b')
    parsed = []
    for r in refs:
        parts = r.split('.')[1:]  # drop leading 'snapshot'
        parsed.append(parts)

    snapshot_obj = build_sample_snapshot()

    missing = []
    for chain in parsed:
        cursor = snapshot_obj
        ok = True
        for comp in chain:
            if isinstance(cursor, dict) and comp in cursor:
                cursor = cursor[comp]
            else:
                ok = False
                break
        if not ok:
            missing.append('.'.join(['snapshot'] + chain))

    # Special-case: footer fragment can use footer_panel.footer.* path; ensure at least one path present
    if template_name == '_footer_fragment.html':
        # If snapshot.footer.* missing but envelope present, treat as satisfied.
        # We simply assert no missing entries unless they start with snapshot.footer and appear in footer enveloped.
        reconciled = []
        for m in missing:
            if m.startswith('snapshot.footer.'):
                # does footer enveloped contain field?
                fname = m.split('.')[-1]
                if fname in FOOTER_ENVELOPED['footer']:
                    continue
            reconciled.append(m)
        missing = reconciled

    assert not missing, f"Missing sample keys for: {missing}"
