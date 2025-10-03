"""Schema validation tests for PanelsWriter artifacts.

Covers:
- Manifest validates against JSON schema.
- Each referenced panel file validates against generic panel schema.
- Intentional mutation triggers validation failure (negative test).
"""
from __future__ import annotations

import json
from pathlib import Path
import os
import shutil

from scripts.summary.plugins.base import PanelsWriter, TerminalRenderer, SummarySnapshot
from scripts.summary.unified_loop import UnifiedLoop
from src.panels.validate import validate_manifest, validate_panel_generic, validate_directory


def _build_dummy_snapshot(cycle: int = 1):
    # Provide minimal required fields for panels schema (PanelsWriter wraps each panel payload
    # with an object requiring 'updated_at'; internal panel extraction also expects certain
    # sub-objects. We include representative sections with stable dummy values.
    status = {
        "indices_detail": {
            "NIFTY": {"status": "OK", "dq": {"score_percent": 88.0}, "age": 1.2},
        },
        "alerts": [{"time": "2025-09-30T00:00:00Z", "level": "INFO", "component": "Test", "message": "ok"}],
        "memory": {"rss_mb": 123.4},
        "loop": {"cycle": cycle, "last_duration": 0.05, "target_interval": 1.0},
        "performance": {"build_ms": 12},
        "analytics": {"some_metric": 42},
        "app": {"version": "1.2.3"},
    }
    snap = SummarySnapshot(
        status=status,
        derived={"indices_count": 1, "alerts_total": 1},
        panels={},
        ts_read=0.0,
        ts_built=0.1,
        cycle=cycle,
        errors=(),
    )
    return snap


def test_manifest_and_panels_validate(tmp_path: Path):
    panels_dir = tmp_path / "panels"
    pw = PanelsWriter(panels_dir=str(panels_dir))
    pw.setup({})
    pw.process(_build_dummy_snapshot())
    # Validate directory
    results = validate_directory(panels_dir)
    # All results should be True
    assert results, "Expected some validation results"
    assert all(results.values()), f"Validation failures: {results}"
    # Direct manifest validation
    assert validate_manifest(panels_dir / "manifest.json")
    # Validate each referenced panel path
    with open(panels_dir / "manifest.json", "r", encoding="utf-8") as f:
        mf = json.load(f)
    for fname in mf["files"]:
        assert validate_panel_generic(panels_dir / fname), fname


def test_manifest_mutation_fails(tmp_path: Path):
    panels_dir = tmp_path / "panels"
    pw = PanelsWriter(panels_dir=str(panels_dir))
    pw.setup({})
    pw.process(_build_dummy_snapshot())
    manifest_path = panels_dir / "manifest.json"
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    # Remove required field
    manifest.pop("generator", None)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    assert not validate_manifest(manifest_path)
