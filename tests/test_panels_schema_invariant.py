"""Panels schema invariant test.

Ensures emitted panel JSON artifacts contain ONLY the expected top-level keys
and that no transitional duplication fields (items, count, memory_rss_mb, etc.)
leak back to the top-level outside the canonical wrapper shape.

Canonical shape (per panel JSON file):
{
  "panel": <str>,
  "updated_at": <ISO8601>,
  "data": { ... domain-specific content ... }
}
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

PANELS_DIR = Path("data/panels")

EXPECTED_TOP_LEVEL = {"panel", "updated_at", "data"}
# Fields that must NOT appear at the top level anymore (formerly duplicated for indices/system).
PROHIBITED_TOP_LEVEL = {"items", "count", "memory_rss_mb", "cycle", "interval", "last_duration"}

@pytest.mark.integration
def test_panels_schema_invariants(snapshot_builder=None):  # snapshot_builder fixture name reserved if added later
    if not PANELS_DIR.exists():
        pytest.skip("Panels directory not present – nothing to validate")

    panel_files = sorted(p for p in PANELS_DIR.glob("*_panel.json"))
    if not panel_files:
        pytest.skip("No panel JSON files to validate")

    violations = []
    for pf in panel_files:
        with pf.open("r", encoding="utf-8") as fh:
            try:
                payload = json.load(fh)
            except json.JSONDecodeError as e:
                violations.append(f"{pf.name}: invalid JSON ({e})")
                continue

        top_keys = set(payload.keys())
        unexpected = top_keys - EXPECTED_TOP_LEVEL
        if unexpected:
            violations.append(f"{pf.name}: unexpected top-level keys {sorted(unexpected)}")

        prohibited = top_keys & PROHIBITED_TOP_LEVEL
        if prohibited:
            violations.append(f"{pf.name}: prohibited resurrected keys {sorted(prohibited)}")

        # Basic presence assertions
        for required in EXPECTED_TOP_LEVEL:
            if required not in payload:
                violations.append(f"{pf.name}: missing required key '{required}'")

        # Light sanity checks (non-empty panel name, data struct)
        if isinstance(payload.get("panel"), str) and not payload["panel"]:
            violations.append(f"{pf.name}: empty panel name")
        if not isinstance(payload.get("data"), dict):
            violations.append(f"{pf.name}: data must be an object/dict")

    if violations:
        formatted = "\n".join(violations)
        pytest.fail(f"Panel schema invariant violations:\n{formatted}")
