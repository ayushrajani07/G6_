from __future__ import annotations
import json
import os
from typing import Any, Dict

from src.panels.factory import build_panels
from src.utils.status_reader import StatusReader

class _StubReader(StatusReader):  # type: ignore[misc]
    def __init__(self, status_obj: Dict[str, Any]):  # type: ignore[override]
        self._status_obj = status_obj
    def get_raw_status(self) -> Dict[str, Any]:  # type: ignore[override]
        return self._status_obj
    # Disable underlying unified source lookups for this focused test
    def get_cycle_data(self):  # type: ignore[override]
        return {}
    def get_indices_data(self):  # type: ignore[override]
        return {}
    def get_resources_data(self):  # type: ignore[override]
        return {}
    def get_provider_data(self):  # type: ignore[override]
        return {}
    def get_health_data(self):  # type: ignore[override]
        return {}


def test_adaptive_alerts_panel_structure():
    status = {
        "adaptive_alerts": [
            {"type": "interpolation_high", "message": "interp fraction > threshold for NIFTY"},
            {"type": "risk_delta_drift", "message": "risk delta drift +30% over 5 builds"},
            {"type": "bucket_util_low", "message": "bucket utilization 0.60 < 0.70 for 5 builds"},
            {"type": "interpolation_high", "message": "interp fraction > threshold for BANKNIFTY"},
        ]
    }
    reader = _StubReader(status)
    panels = build_panels(reader, status)
    assert "adaptive_alerts" in panels, "adaptive_alerts panel missing"
    panel = panels["adaptive_alerts"]
    assert isinstance(panel, dict)
    assert panel.get("total") == 4
    by_type = panel.get("by_type")
    assert isinstance(by_type, dict)
    # Verify counts aggregated correctly
    assert by_type.get("interpolation_high") == 2
    assert by_type.get("risk_delta_drift") == 1
    assert by_type.get("bucket_util_low") == 1
    recent = panel.get("recent")
    assert isinstance(recent, list) and len(recent) <= 10
    # Last alert type matches most recent entry
    last = panel.get("last")
    assert isinstance(last, dict)
    assert last.get("type") == status["adaptive_alerts"][-1]["type"]
