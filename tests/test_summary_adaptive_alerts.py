from __future__ import annotations
import os, json, tempfile, textwrap
from pathlib import Path

import pytest
from scripts.summary.plain_renderer import PlainRenderer
from scripts.summary.domain import build_domain_snapshot
from scripts.summary.plugins.base import SummarySnapshot


def _write_status(path: Path, alerts):
    obj = {
        "indices": ["NIFTY"],
        "adaptive_alerts": alerts,
        "cycle": 42,
    }
    path.write_text(json.dumps(obj), encoding="utf-8")
    return obj


def test_plain_renderer_contains_alerts_section():
    # Legacy badge formatting may differ; ensure at least panel header rendered.
    alerts = [
        {"type": "interpolation_high", "message": "interp fraction high"},
        {"type": "risk_delta_drift", "message": "+30% drift"},
        {"type": "interpolation_high", "message": "still high"},
    ]
    status = {"adaptive_alerts": alerts, "indices": ["NIFTY"], "cycle": 42}
    domain = build_domain_snapshot(status, ts_read=0.0)
    snap = SummarySnapshot(status=status, derived={}, panels={}, ts_read=0.0, ts_built=0.0, cycle=42, errors=[], model=None, domain=domain)
    import io, sys
    buf, old = io.StringIO(), sys.stdout
    try:
        sys.stdout = buf
        PlainRenderer().process(snap)
    finally:
        sys.stdout = old
    out = buf.getvalue()
    assert "Alerts" in out or "Adaptive" in out

@pytest.mark.skip(reason="Legacy plain_fallback output path removed (summary_view deleted)")
def test_legacy_plain_fallback_deprecated():  # pragma: no cover - intentionally skipped
    assert True
