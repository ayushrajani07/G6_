from __future__ import annotations
import os, json, tempfile, textwrap
from pathlib import Path

from scripts.summary_view import plain_fallback


def _write_status(path: Path, alerts):
    obj = {
        "indices": ["NIFTY"],
        "adaptive_alerts": alerts,
        "cycle": 42,
    }
    path.write_text(json.dumps(obj), encoding="utf-8")
    return obj


def test_plain_fallback_includes_adaptive_alerts_badge():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)/'status.json'
        alerts = [
            {"type": "interpolation_high", "message": "interp fraction high"},
            {"type": "risk_delta_drift", "message": "+30% drift"},
            {"type": "interpolation_high", "message": "still high"},
        ]
        _write_status(p, alerts)
        text = plain_fallback(json.loads(p.read_text(encoding='utf-8')), str(p), None)
        # Expect badge line
        assert 'Adaptive alerts:' in text
        # Total should be 3
        assert 'Adaptive alerts: 3' in text
        # top type interpolation_high count 2 likely present
        assert 'interpolation_high:2' in text or 'interpolation_high: 2' in text
