import os
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

# Scan only active runtime Python (exclude archived + removed stub).
PATTERNS = [
    re.compile(r"python\s+-m\s+src\.unified_main"),
    re.compile(r"G6_ENABLE_LEGACY_LOOP"),
    re.compile(r"G6_SUPPRESS_LEGACY_LOOP_WARN"),
]

def test_no_legacy_loop_tokens_remaining():
    if os.environ.get("G6_ALLOW_LEGACY_SCAN"):
        pytest.skip("Safeguard disabled via G6_ALLOW_LEGACY_SCAN=1")
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if not path.is_file():
            continue
        if path.name == "unified_main.py":  # fail-fast stub
            continue
        if "archived" in path.parts:  # historical references allowed
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in PATTERNS:
            if pat.search(text):
                offenders.append(f"{path}: {pat.pattern}")
    assert not offenders, (
        "Legacy loop tokens unexpectedly present in active runtime source (exclude archived & stub):\n"
        + "\n".join(offenders)
    )
