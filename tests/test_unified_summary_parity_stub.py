"""Parity stub test for future unified loop vs legacy processes.

Will be expanded in Phase 2 to compare JSON panel artifacts and terminal summary
aggregates. For now it simply verifies the skeleton UnifiedLoop can run a
few cycles with placeholder plugins without raising.
"""
from __future__ import annotations

import json, os, time
import pytest

from scripts.summary.unified_loop import UnifiedLoop
from scripts.summary.plugins.base import TerminalRenderer, PanelsWriter, MetricsEmitter


def test_unified_loop_parity_basic(tmp_path, monkeypatch):
    """Exercise unified loop end-to-end and assert panel artifact consistency.

    Scope:
      - Run 3 cycles with PanelsWriter in expanded mode (default) writing into tmp_path.
    - Assert required enveloped panel files created (indices_panel_enveloped, alerts_enveloped, system_enveloped, performance_enveloped, manifest).
      - Verify manifest enumerates those files and reference cycle matches unified_snapshot.json.
      - Basic sanity of indices_panel.json structure (items array) and system.json keys.
      - Confirm errors list in unified_snapshot.json is empty (or present list type).
    This does not compare against legacy bridge yet; that will come once a stable
    legacy fixture harness is defined for side-by-side execution.
    """
    # Point panels dir env to tmp so any indirect helpers follow same path
    monkeypatch.setenv("G6_PANELS_DIR", str(tmp_path))
    status_file = tmp_path / "runtime_status.json"
    # Minimal synthetic status file to drive indices + memory + alerts
    status_file.write_text(json.dumps({
        "loop": {"cycle": 0, "last_duration": 0.01, "target_interval": 0.1},
        "interval": 0.1,
        "indices_detail": {
            "NIFTY": {"status": "OK", "dq": {"score_percent": 97.5}, "age": 1.2},
            "BANKNIFTY": {"status": "OK", "dq": {"score_percent": 88.1}, "age": 2.0},
        },
        "alerts": [
            {"time": "2025-09-30T12:00:00Z", "level": "INFO", "component": "Test", "message": "hello"}
        ],
        "memory": {"rss_mb": 123.4},
        "performance": {"options_per_min": 1234, "cycles_per_hour": 99},
        "app": {"version": "1.2.3"},
    }), encoding="utf-8")
    monkeypatch.setenv("G6_SUMMARY_STATUS_FILE", str(status_file))
    loop = UnifiedLoop([
        TerminalRenderer(rich_enabled=False),  # plain path
        PanelsWriter(panels_dir=str(tmp_path)),
        MetricsEmitter(),
    ], panels_dir=str(tmp_path), refresh=0.01)
    loop.run(cycles=3)
    # Required files
    required = [
        "unified_snapshot.json",
        "indices_panel_enveloped.json",
        "alerts_enveloped.json",
        "system_enveloped.json",
        "performance_enveloped.json",
        "manifest.json",
    ]
    for fname in required:
        assert (tmp_path / fname).exists(), f"Expected panel artifact {fname} missing"
    snap = json.loads((tmp_path / "unified_snapshot.json").read_text(encoding="utf-8"))
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(snap.get("cycle"), int) and snap["cycle"] >= 1
    assert manifest.get("cycle") == snap.get("cycle")
    # New manifest metadata
    assert manifest.get("schema_version") == 1
    assert manifest.get("generator") == "PanelsWriter"
    assert isinstance(manifest.get("indices_count"), int)
    assert isinstance(manifest.get("alerts_total"), int)
    assert manifest.get("app_version") == "1.2.3"
    files_list = manifest.get("files") or []
    # Ensure manifest lists at least the required subset (excluding unified_snapshot.json itself)
    # Manifest lists panel artifact files (excluding unified_snapshot.json and manifest.json itself)
    for expected in [f for f in required if f not in {"unified_snapshot.json", "manifest.json"}]:
        assert expected in files_list, f"manifest missing {expected}"
    # Structural checks
    indices_panel = json.loads((tmp_path / "indices_panel_enveloped.json").read_text(encoding="utf-8"))
    # Wrapped schema: root keys panel, updated_at, data
    # Enveloped panel reports logical name 'indices_panel_enveloped' (file base without .json)
    assert indices_panel.get("panel") in ("indices_panel","indices_panel_enveloped")
    assert isinstance(indices_panel.get("data"), dict)
    assert "items" in indices_panel["data"] and isinstance(indices_panel["data"]["items"], list)
    system_panel = json.loads((tmp_path / "system_enveloped.json").read_text(encoding="utf-8"))
    assert system_panel.get("panel") == "system"
    assert isinstance(system_panel.get("data"), dict)
    for key in ("memory_rss_mb", "cycle", "interval"):
        assert key in system_panel["data"]
    # errors list (can be empty)
    assert isinstance(snap.get("errors"), list)
    # Basic coherence: indices_count matches indices_panel count
    if isinstance(snap.get("indices_count"), int):
        assert snap["indices_count"] == indices_panel.get("data", {}).get("count")
    # alerts_total matches alerts length
    alerts_panel = json.loads((tmp_path / "alerts_enveloped.json").read_text(encoding="utf-8"))
    if isinstance(snap.get("alerts_total"), int) and isinstance(alerts_panel, list):
        # Some builders may count multiple alert categories internally; ensure at least the displayed alerts length.
        assert snap["alerts_total"] >= len(alerts_panel)
