import os
import re
from pathlib import Path

import pytest


ENABLED = os.getenv('G6_ENV_ADAPTER_LINT', '').lower() in {'1','true','yes','on'}


@pytest.mark.skipif(not ENABLED, reason='Set G6_ENV_ADAPTER_LINT=1 to enable env adapter lint')
def test_no_direct_env_usage_in_core_packages():
    base = Path(__file__).resolve().parents[1]
    targets = [
        base / 'src' / 'collectors',
        base / 'src' / 'events',
        base / 'src' / 'storage',
    ]
    # Allowlist: test-only helpers or specific files that intentionally use os.environ/os.getenv
    allowlist = {
        # Add relative paths from repo root if exceptions are required
    }
    pattern = re.compile(r"os\.environ\[|os\.getenv\(|getenv\(")
    offenders = []
    for target in targets:
        if not target.exists():
            continue
        for path in target.rglob('*.py'):
            rel = path.relative_to(base)
            if str(rel) in allowlist:
                continue
            try:
                text = path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue
            if pattern.search(text):
                offenders.append(str(rel))
    assert not offenders, f"Direct env usage found in core packages (use env_adapter): {sorted(set(offenders))[:50]}"
