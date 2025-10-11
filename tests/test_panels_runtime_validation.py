from __future__ import annotations

import json
import os
from pathlib import Path
import pytest

from scripts.summary.plugins.base import PanelsWriter, SummarySnapshot


def _snapshot():
    status = {
        "indices_detail": {"NIFTY": {"status": "OK", "dq": {"score_percent": 90.0}, "age": 1.0}},
        "alerts": [],
        "memory": {"rss_mb": 100.0},
        "loop": {"cycle": 1, "last_duration": 0.01, "target_interval": 1.0},
    }
    return SummarySnapshot(
        status=status,
        derived={"indices_count": 1, "alerts_total": 0},
        panels={},
        ts_read=0.0,
        ts_built=0.1,
        cycle=1,
        errors=(),
    )


def test_runtime_validation_warn_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("G6_PANELS_VALIDATE", "warn")
    panels_dir = tmp_path / "panels"
    pw = PanelsWriter(panels_dir=str(panels_dir))
    pw.setup({})
    pw.process(_snapshot())
    # Should create manifest & at least indices_panel_enveloped.json (legacy name removed by default)
    manifest = panels_dir / "manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert any(f.endswith("indices_panel_enveloped.json") for f in data.get("files", []))


def test_runtime_validation_strict_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("G6_PANELS_VALIDATE", "strict")
    panels_dir = tmp_path / "panels"
    pw = PanelsWriter(panels_dir=str(panels_dir))
    pw.setup({})
    # Wrap validator so it corrupts payload pre-validation.
    orig_validate = pw._validate_fn  # type: ignore[attr-defined]
    assert orig_validate is not None, "Expected validation function to be present"

    def corrupt_then_validate(payload):  # noqa: ANN001
        if isinstance(payload, dict):
            # In enveloped path updated_at may exist at top-level OR inside wrapper depending on migration stage
            if (payload.get("panel") or "").startswith("indices_panel"):
                payload.pop("updated_at", None)
        return orig_validate(payload)

    pw._validate_fn = corrupt_then_validate  # type: ignore
    with pytest.raises(ValueError):
        pw.process(_snapshot())
